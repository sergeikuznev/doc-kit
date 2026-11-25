#!/usr/bin/env python3
"""
doc.py - fill-in-the-blanks engineering documentation for hardware projects.
https://github.com/sergeikuznev/doc-kit

Asks you the questions for each document type and writes your answers,
word for word, into the right file with the right structure.
Nothing is generated or guessed: you supply all the content.

Set up a project (run from the doc-kit folder, once per project):
    python3 doc.py init /path/to/your/project

Then, from anywhere inside that project:
    python3 tools/doc.py              menu: "what just happened?"
    python3 tools/doc.py idea         new idea, created as a GitHub issue
    python3 tools/doc.py bug          new bug, created as a GitHub issue
    python3 tools/doc.py decision     new decision record
    python3 tools/doc.py req          new requirement
    python3 tools/doc.py test ID      record a test result for a requirement
    python3 tools/doc.py fault        new row in the fault table
    python3 tools/doc.py procedure    new procedure
    python3 tools/doc.py check        new pre-power checklist line
    python3 tools/doc.py log          devlog entry for this week
    python3 tools/doc.py update [ID]  change a status, text or link written earlier
    python3 tools/doc.py report       status page: docs/report.html (opens in browser)
    python3 tools/doc.py tidy         regroup requirements.md by subsystem
    python3 tools/doc.py install-hook ask after commits that close an issue

Type < at any question to go back one step (inside a list, < removes the
last line). Type << to see all your answers so far and jump to any of them.
Ctrl+C at any point cancels without writing anything.
"""

__version__ = "0.1.0"

import datetime
import html
import os
import re
import shutil
import subprocess
import sys
import textwrap

try:
    import readline as _rl  # line editing, history, and pre-filled answers
except ImportError:
    _rl = None

DEFAULT_PREFIXES = [
    ("SYS", "Whole system"),
    ("COMM", "Communications"),
    ("PWR", "Power"),
    ("MOT", "Motors and actuators"),
    ("SENS", "Sensors and perception"),
    ("SW", "Software"),
    ("MECH", "Mechanical"),
    ("FDIR", "Fault detection, isolation and recovery"),
]
METHODS = [("T", "Test"), ("I", "Inspection"), ("A", "Analysis"), ("D", "Demonstration")]
SEVERITY = [("1", "Annoying"), ("2", "Mission degraded"), ("3", "Mission lost"), ("4", "Hardware damage")]

REQ_HEADER = "| ID | Requirement | Rationale | Method | Status | Evidence |"
FDIR_HEADER = "| ID | Failure | Effect | Detection | Isolation / response | Recovery | Sev | Req |"
HIST_HEADER = "| Date | Line added | Why |"


# ----------------------------------------------------------------- terminal

def c(text, code):
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def info(msg):
    print(c(msg, "2"))

def warn(msg):
    print(c("! " + msg, "33"))

def ok(msg):
    print(c(msg, "32"))


# ----------------------------------------------------------------- arrow-key menus
#
# In a real terminal every choice is a menu: arrow keys to move, Enter to
# select, type to filter. Piped input (scripts, tests) and terminals without
# termios (Windows) fall back to typing a number or key. DOC_PLAIN=1 forces
# the fallback.

try:
    import select
    import termios
    import tty
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

MENU_HINT = "↑↓ move · Enter select · type to filter · < back · << jump"

def interactive():
    return (_HAS_TERMIOS and sys.stdin.isatty() and sys.stdout.isatty()
            and os.environ.get("DOC_PLAIN") != "1")

class _Raw:
    """Read single keys without echo; always restores the terminal."""
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
        return self

    def __exit__(self, *exc):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()

_ESC_KEYS = {b"[A": "up", b"OA": "up", b"[B": "down", b"OB": "down",
             b"[C": "right", b"OC": "right", b"[D": "left", b"OD": "left",
             b"[5~": "pgup", b"[6~": "pgdn", b"[H": "home", b"OH": "home",
             b"[F": "end", b"OF": "end", b"[1~": "home", b"[4~": "end", b"[3~": "delete",
             b"b": "wordleft", b"f": "wordright", b"[1;3D": "wordleft", b"[1;3C": "wordright",
             b"[1;5D": "wordleft", b"[1;5C": "wordright", b"[1;9D": "wordleft", b"[1;9C": "wordright",
             b"[1;2H": "home", b"[1;2F": "end"}
_CTRL_KEYS = {b"\x01": "home", b"\x05": "end", b"\x02": "left", b"\x06": "right",
              b"\x15": "killline", b"\x0b": "killend", b"\x17": "killword"}

def _read_key(fd):
    b = os.read(fd, 1)
    if b == b"\x1b":
        seq = b""
        while select.select([fd], [], [], 0.03)[0]:
            seq += os.read(fd, 1)
            if len(seq) >= 2 and (seq[-1:].isalpha() or seq[-1:] == b"~"):
                break
        return _ESC_KEYS.get(seq, "esc" if not seq else None)
    if b in (b"\r", b"\n"):
        return "enter"
    if b in (b"\x7f", b"\x08"):
        return "backspace"
    if b == b"\x03":
        raise KeyboardInterrupt
    if b == b"\x04":
        raise EOFError
    if b in _CTRL_KEYS:
        return _CTRL_KEYS[b]
    if b[0] >= 0xC0:                      # multi-byte UTF-8 character
        extra = 1 if b[0] < 0xE0 else 2 if b[0] < 0xF0 else 3
        b += os.read(fd, extra)
    try:
        ch = b.decode()
    except UnicodeDecodeError:
        return None
    return ch if ch.isprintable() else None

def _width():
    return max(40, shutil.get_terminal_size((80, 24)).columns)

def _fit(text, room):
    return text if len(text) <= room else text[:max(1, room - 1)] + "…"

def _cells(text):
    """Terminal columns a string takes (wide East Asian characters count as 2)."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)

def line_edit(prompt, text=""):
    """A small line editor with the line pre-filled. Works the same with any
    readline library (macOS libedit ignores pre-fill hooks)."""
    buf, cur, row = list(text or ""), len(text or ""), 0
    with _Raw() as raw:
        sys.stdout.write("\x1b[?25h")             # keep the cursor visible while typing
        while True:
            width = _width()
            line = prompt + "".join(buf)
            total = _cells(line)
            sys.stdout.write("\r" + (f"\x1b[{row}A" if row else "") + "\x1b[J" + line)
            if total and total % width == 0:
                sys.stdout.write(" \b")             # leave the pending-wrap state
            end_row = total // width
            target = _cells(prompt + "".join(buf[:cur]))
            row, col = target // width, target % width
            if end_row > row:
                sys.stdout.write(f"\x1b[{end_row - row}A")
            sys.stdout.write("\r" + (f"\x1b[{col}C" if col else ""))
            sys.stdout.flush()

            key = _read_key(raw.fd)
            if key == "enter":
                down = end_row - row
                sys.stdout.write((f"\x1b[{down}B" if down else "") + "\r\n")
                sys.stdout.flush()
                return "".join(buf)
            if key == "left":
                cur = max(0, cur - 1)
            elif key == "right":
                cur = min(len(buf), cur + 1)
            elif key == "home":
                cur = 0
            elif key == "end":
                cur = len(buf)
            elif key == "backspace" and cur:
                del buf[cur - 1]
                cur -= 1
            elif key == "delete" and cur < len(buf):
                del buf[cur]
            elif key == "killline":
                buf, cur = [], 0
            elif key == "killend":
                del buf[cur:]
            elif key in ("wordleft", "killword"):
                j = cur
                while j and buf[j - 1] == " ":
                    j -= 1
                while j and buf[j - 1] != " ":
                    j -= 1
                if key == "killword":
                    del buf[j:cur]
                cur = j
            elif key == "wordright":
                j = cur
                while j < len(buf) and buf[j] == " ":
                    j += 1
                while j < len(buf) and buf[j] != " ":
                    j += 1
                cur = j
            elif key and len(key) == 1:
                buf.insert(cur, key)
                cur += 1


PANE_MAX = 10      # most lines the preview pane shows

def _pane(text, room):
    """Preview pane lines for the highlighted option (first line is the title)."""
    rows = []
    for para in text.split("\n"):
        indent = " " * (len(para) - len(para.lstrip()))
        rows += textwrap.wrap(para, max(20, room - 4), subsequent_indent=indent) or [""]
    if len(rows) > PANE_MAX:
        rows = rows[:PANE_MAX - 1] + [f"… {len(rows) - PANE_MAX + 1} more lines"]
    out = [c("  ┌ ", "36") + c(rows[0], "1")]
    out += [c("  │ ", "36") + r for r in rows[1:]]
    return out + [c("  └", "36")]

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

def _rows(lines):
    """Terminal rows these lines occupy, counting embedded newlines and wrapping."""
    width = _width()
    total = 0
    for line in lines:
        for part in _ANSI_RE.sub("", line).split("\n"):
            total += max(1, -(-_cells(part) // width))
    return total

def menu(prompt, options, default=None, nav=True, details=None):
    """Arrow-key menu. options: list of (key, label). Returns the chosen key.
    details: optional full text per option, shown in a preview pane under the
    list for the highlighted option (otherwise the pane appears only when a
    label is cut off). With nav=True, '<' raises Back and '<<' opens the
    jump picker."""
    width = max(len(k) for k, _ in options)
    labels = [lab if k == lab else f"{k:<{width}}  {lab}" for k, lab in options]
    keys = [k for k, _ in options]
    idx = keys.index(default) if default in keys else 0
    flt, top, drawn = "", 0, 0
    # Leading blank lines in the prompt are printed once, not redrawn:
    # the redraw moves the cursor up by the number of rows it drew.
    lead = len(prompt) - len(prompt.lstrip("\n"))
    if lead:
        sys.stdout.write("\n" * lead)
        prompt = prompt.lstrip("\n")

    def clear():
        nonlocal drawn
        if drawn:
            sys.stdout.write(f"\x1b[{drawn}A\x1b[J")
            drawn = 0

    with _Raw() as raw:
        while True:
            shown = [i for i, lab in enumerate(labels) if flt.lower() in lab.lower()]
            if shown and idx not in shown:
                idx = shown[0]
            pos = shown.index(idx) if shown else 0
            room = _width() - 6
            pane = []
            if shown:
                full = details[idx] if details and details[idx] else None
                if not full and _cells(labels[idx]) > room:
                    full = labels[idx]
                if full:
                    pane = _pane(full, room)
            visible = max(3, min(12, shutil.get_terminal_size((80, 24)).lines - 6 - len(pane)))
            top = min(max(top, pos - visible + 1), pos)
            top = max(0, min(top, max(0, len(shown) - visible)))
            out = [c(prompt, "1") + (c(f"   filter: {flt}", "33") if flt else "")]
            out.append(c("    ↑ more", "2") if top > 0 else "")
            for i in shown[top:top + visible]:
                if i == idx:
                    out.append(c("  ❯ " + _fit(labels[i], room), "1;36"))
                else:
                    out.append("    " + _fit(labels[i], room))
            if not shown:
                out.append(c("    no match, Backspace clears the filter", "2"))
            out.append(c("    ↓ more", "2") if top + visible < len(shown) else "")
            out += pane
            out.append(c("  " + (MENU_HINT if nav else "↑↓ move · Enter select · type to filter"), "2"))
            clear()
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
            drawn = _rows(out)

            key = _read_key(raw.fd)
            if key in ("up", "down") and shown:
                step = -1 if key == "up" else 1
                idx = shown[(pos + step) % len(shown)]
            elif key in ("pgup", "pgdn") and shown:
                step = -visible if key == "pgup" else visible
                idx = shown[max(0, min(len(shown) - 1, pos + step))]
            elif key == "home" and shown:
                idx = shown[0]
            elif key == "end" and shown:
                idx = shown[-1]
            elif key == "enter" and shown:
                clear()
                print(c(prompt, "1") + ("  " if prompt else "") + c(options[idx][1] if options[idx][0] == options[idx][1]
                      else f"{options[idx][0]}  {options[idx][1]}", "36"))
                return keys[idx]
            elif key == "backspace":
                flt = flt[:-1]
            elif key == "esc":
                flt = ""
            elif key == "<" and nav and not flt:
                second = select.select([raw.fd], [], [], 0.4)[0] and os.read(raw.fd, 1) == b"<"
                clear()
                if not second:
                    raise Back
                pick = jump_picker()
                if pick is not None:
                    raise Jump(pick)
            elif key and len(key) == 1:
                flt += key

def jump_picker():
    """Menu of all answers (including ones still waiting to come back).
    Returns an index into timeline(), or None to stay."""
    items, here = timeline()
    if not items:
        warn("Nothing answered yet.")
        return None
    opts, details = [("stay", "Stay where I am")], [None]
    for i, (_, prompt, val) in enumerate(items, 1):
        mark = "   ← editing now" if i - 1 == here else ""
        short = prompt.split(":")[0].strip() if ":" in prompt and len(prompt.split(":")[0]) <= 30 else prompt
        opts.append((str(i), f"{short}: {_show(val)}{mark}"))
        body = "\n".join(val) if isinstance(val, list) and val else _show(val)
        details.append(f"{prompt}{'  (editing now)' if mark else ''}\n{body}")
    pick = menu(c("Change which answer?", "35"), opts, nav=False, details=details)
    return None if pick == "stay" else int(pick) - 1

# ----------------------------------------------------------------- going back / jumping
#
# "<"  at a question goes back one question.
# "<<" at a question lists every answer so far; pick one to change it.
#
# Both work by restarting the command and replaying the earlier answers
# automatically, so any flow (including loops) can be rewound safely.
# After a jump, the answers that came after the edited one are replayed too.
# If the edit changes the flow (e.g. one option more), only the new questions
# are asked; saved answers to questions that still exist are kept.
# Nothing is written to disk until the final confirmation.

BACK, JUMP = "<", "<<"

class Back(Exception):
    pass

class Jump(Exception):
    def __init__(self, index):
        self.index = index

class _Ask:
    """Marker in REPLAY: ask this question interactively. Carries the old
    answer so it can be pre-filled and is never lost by a second jump."""
    def __init__(self, item=None):
        self.item = item

CURRENT = None     # old answer of the question being re-asked right now
PENDING = None     # what was typed into the current question when < or << was used
ANSWERS = []       # (key, prompt, value) for answers given in the current run
REPLAY = []        # (key, prompt, value) or ASK, filled in automatically
PREFILL = {}       # key -> previous answer, offered for editing after < or <<

def _prefill(prompt):
    """The previous answer to this question, if we just went back/jumped to it."""
    return PREFILL.pop(_key(prompt), None)

def _input(prompt, text=None):
    """Read one line. In a terminal: doc's own editor, pre-filled with text."""
    if interactive():
        return line_edit(prompt, text or "")
    return input(prompt)

def _key(prompt):
    """Question identity, ignoring names in quotes ("Pros of 'X'") and spacing."""
    return re.sub(r"'[^']*'", "''", " ".join(prompt.split())).lower()

def _show(val):
    if isinstance(val, list):
        return "; ".join(val) or "(none)"
    if val is True:
        return "yes"
    if val is False:
        return "no"
    return val or "(empty)"

def _replayed(prompt):
    """If an answer is queued for this question, use it and echo it."""
    global CURRENT
    if not REPLAY:
        return False, None
    if isinstance(REPLAY[0], _Ask):
        marker = REPLAY.pop(0)
        CURRENT = marker.item
        if marker.item is not None:
            PREFILL[_key(prompt)] = marker.item[2]
        return False, None
    key = _key(prompt)
    # The saved answer for this question may be further along if an edit
    # removed some questions (e.g. one option fewer): skip to it.
    for i, item in enumerate(REPLAY):
        if not isinstance(item, _Ask) and item[0] == key:
            del REPLAY[:i + 1]
            ANSWERS.append(item)
            info(f"  {prompt.strip() or 'choice'}: {_show(item[2])}")
            return True, item[2]
    # A question that was not asked before (e.g. one option more): ask it,
    # and keep the saved answers for the questions after it.
    return False, None

def _record(prompt, val):
    global CURRENT, PENDING
    ANSWERS.append((_key(prompt), prompt.strip() or "choice", val))
    CURRENT = PENDING = None
    return val

def _hold(prompt, value):
    """Remember what has been typed into this question before jumping away,
    so the edit is not lost. Empty input keeps the previous answer."""
    global PENDING
    PENDING = (_key(prompt), prompt.strip() or "choice", value) if value else None

def timeline():
    """Every answer of this run in order: answered so far, the one being
    re-asked now (if we jumped to it), and the ones still waiting to replay.
    Returns (items, index of the question being asked now or None)."""
    items = list(ANSWERS)
    here = None
    cur = PENDING if PENDING is not None else CURRENT
    if cur is not None:
        here = len(items)
        items.append(cur)
    items += [r for r in REPLAY if not isinstance(r, _Ask)]
    return items, here

def _special(ans):
    """Handle < and <<. Returns True if the caller should re-ask the question."""
    if ans == BACK:
        raise Back
    if ans == JUMP and interactive():
        pick = jump_picker()
        if pick is None:
            return True
        raise Jump(pick)
    if ans == JUMP:
        items, _ = timeline()
        if not items:
            warn("Nothing answered yet.")
            return True
        print(c("\nYour answers so far:", "1;35"))
        for i, (_, prompt, val) in enumerate(items, 1):
            text = _show(val)
            print(f"  {i:>2}) {prompt}: {text if len(text) <= 70 else text[:67] + '...'}")
        while True:
            pick = input("  change which? (number, Enter to stay here): ").strip()
            if not pick:
                print()
                return True
            if pick.isdigit() and 1 <= int(pick) <= len(items):
                raise Jump(int(pick) - 1)
            warn("Type a number from the list, or press Enter.")
    return False

def ask(prompt, required=True, default=None, hint=None):
    """One line of input. Re-asks if required and empty."""
    done, val = _replayed(prompt)
    if done:
        return val
    # Question on its own line, plain "> " for input: colour codes inside
    # input() confuse line editing on macOS and garble the prompt.
    suffix = f" [{default}]" if default else ""
    pre = _prefill(prompt)
    pre = pre if isinstance(pre, str) and pre else None
    while True:
        print(c(prompt + suffix, "1"))
        if hint:
            info("  " + hint)
        if pre:
            info("  your previous answer is filled in: edit it, or Enter to keep it (<< at the end jumps)")
        while True:
            ans = _input("> ", pre).strip()
            typed = ans
            pre = None
            if ans.endswith(JUMP) and ans != JUMP:      # "some text<<": jump, keep the text
                typed, ans = ans[:-len(JUMP)].rstrip(), JUMP
            if ans == JUMP:
                _hold(prompt, typed if typed not in (JUMP, BACK) else None)
            if _special(ans):
                _hold(prompt, None)
                pre = typed if typed not in (JUMP, BACK) else None   # back after "Stay"
                break
            if not ans and default is not None:
                return _record(prompt, default)
            if ans or not required:
                return _record(prompt, ans)
            warn("This one is required.")

def ask_lines(prompt, required=True, hint=None):
    """Several lines; an empty line finishes. "<" removes the last line,
    or goes back to the previous question if there are no lines yet."""
    done, val = _replayed(prompt)
    if done:
        return val
    pre = _prefill(prompt)
    pre = list(pre) if isinstance(pre, list) and pre else []
    while True:
        print(c(prompt, "1"))
        info("  " + (hint + " " if hint else "") + "(one per line, empty line to finish, < to undo)")
        if pre:
            info("  your previous lines come back one at a time: Enter keeps, edit to change, clear a line to stop there")
        lines = []
        restart = False
        while True:
            line = _input("  > ", pre.pop(0) if pre else None).rstrip()
            if line.strip() == BACK and lines:
                info(f"  removed: {lines.pop()}")
                continue
            kept = None
            if line.rstrip().endswith(JUMP) and line.strip() != JUMP:   # "text<<": jump, keep the text
                kept, line = line.rstrip()[:-len(JUMP)].rstrip(), JUMP
            if line.strip() == JUMP:
                _hold(prompt, lines + ([kept] if kept else []) + pre)
            if line.strip() in (BACK, JUMP):
                if _special(line.strip()):
                    _hold(prompt, None)
                    # "Stay": start the list again with everything typed so far filled in
                    pre = lines + ([kept] if kept else []) + pre
                    restart = True
                    break
            if not line:
                if lines or not required:
                    return _record(prompt, lines)
                warn("Give at least one line.")
                continue
            lines.append(line)
        if restart:
            continue

def ask_choice(prompt, options, default=None, details=None):
    """options: list of (key, label). Returns the key. details: full text
    per option for the preview pane (terminal menus only)."""
    done, val = _replayed(prompt)
    if done:
        return val
    prev = _prefill(prompt)
    if prev in [k for k, _ in options]:
        default = prev
    if interactive():
        return _record(prompt, menu(prompt, options, default, details=details))
    keys = [k.lower() for k, _ in options]
    width = max(len(k) for k, _ in options)
    while True:
        print(c(prompt, "1"))
        for i, (key, label) in enumerate(options, 1):
            print(f"  {i}) {key:<{width}}  {label}" if key != label else f"  {i}) {label}")
        while True:
            ans = input("  choose" + (f" [{default}]" if default else "") + ": ").strip()
            if _special(ans):
                break
            if not ans and default:
                return _record(prompt, default)
            if ans.isdigit() and 1 <= int(ans) <= len(options):
                return _record(prompt, options[int(ans) - 1][0])
            if ans.lower() in keys:
                return _record(prompt, options[keys.index(ans.lower())][0])
            warn("Type a number or a key from the list.")

def yes(prompt, default=False):
    done, val = _replayed(prompt)
    if done:
        return val
    prev = _prefill(prompt)
    if isinstance(prev, bool):
        default = prev
    if interactive():
        pick = menu(prompt, [("yes", "Yes"), ("no", "No")], "yes" if default else "no")
        return _record(prompt, pick == "yes")
    d = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{prompt} [{d}]: ").strip().lower()
        if _special(ans):
            continue
        return _record(prompt, default if not ans else ans.startswith("y"))

def run_with_back(fn):
    """Run a command; on Back or Jump, restart it and replay the kept answers."""
    global ANSWERS, REPLAY, CURRENT, PENDING
    PREFILL.clear()
    keep = []
    first = True
    while True:
        ANSWERS, REPLAY = [], list(keep)
        CURRENT = PENDING = None
        if first:
            info("Enter confirms · < back one step · << jump to any answer · Ctrl+C cancels")
            first = False
        try:
            return fn()
        except Back:
            items, here = timeline()
            now = here if here is not None else len(ANSWERS)    # position of the current question
            PREFILL.clear()
            if now == 0:
                warn("Already at the first question.")
                keep = ([_Ask(items[0])] if here == 0 else []) + items[1 if here == 0 else 0:]
            else:
                keep = items[:now - 1] + [_Ask(items[now - 1])] + items[now:]
            print(c("\n<< back", "35"))
        except Jump as j:
            items, _ = timeline()
            PREFILL.clear()
            keep = items[:j.index] + [_Ask(items[j.index])] + items[j.index + 1:]
            print(c(f"\n<< jumping to: {items[j.index][1]}", "35"))

def preview(title, text):
    room = _width() - 4
    print()
    print(c("┌─ " + title + " " + "─" * max(0, room - len(title) - 2), "36"))
    for line in text.rstrip().splitlines():
        print(c("│ ", "36") + _fit(line, room))
    print(c("└" + "─" * (room + 1), "36"))

def save_menu(prompt, yes_label):
    """Final step: save, change an answer, or cancel. Returns True to save."""
    if not interactive():
        return yes(prompt, default=True)
    while True:
        pick = menu(prompt, [("save", yes_label), ("change", "Change an answer"),
                             ("cancel", "Cancel, write nothing")], "save")
        if pick == "change":
            jump = jump_picker()
            if jump is not None:
                raise Jump(jump)
            continue
        return _record(prompt, pick == "save")

def confirm_write(path, text):
    preview(rel(path), text)
    return save_menu("Write this?", "Write it")


# ----------------------------------------------------------------- repo + files

def find_root():
    d = os.path.abspath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, "docs")) or os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            sys.exit("Could not find the repo root (no docs/ or .git/ above this folder).")
        d = parent

ROOT = None
def p(*parts):
    return os.path.join(ROOT, *parts)

def rel(path):
    return os.path.relpath(path, ROOT)

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    ok(f"Written: {rel(path)}")

def today():
    return datetime.date.today().isoformat()

def slugify(text, maxlen=60):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen].rstrip("-") or "untitled"

def cell(text):
    """Make text safe for one markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


# ----------------------------------------------------------------- markdown tables

def split_row(line):
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [x.strip() for x in re.split(r"(?<!\\)\|", inner)]

def join_row(cells):
    return "| " + " | ".join(cells) + " |"

def find_tables(lines, header):
    """All (header_index, end_index) pairs of tables whose header matches."""
    key = split_row(header)[:2]
    found = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|") and split_row(lines[i])[:2] == key:
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            found.append((i, j))
            i = j
        else:
            i += 1
    return found

def find_table(lines, header):
    """The first matching table, or None."""
    t = find_tables(lines, header)
    return t[0] if t else None

def table_rows(path, header):
    """Rows from every table with this header in the file."""
    if not os.path.exists(path):
        return []
    lines = read(path).splitlines()
    return [split_row(l) for h, e in find_tables(lines, header) for l in lines[h + 2:e]]

def insert_row(text, header, cells):
    lines = text.splitlines()
    t = find_table(lines, header)
    row = join_row(cells)
    if t:
        lines.insert(t[1], row)
    else:
        sep = "|" + "|".join("---" for _ in split_row(header)) + "|"
        lines += ["", header, sep, row]
    return "\n".join(lines) + "\n"

def next_id(rows, prefix):
    nums = [int(m.group(1)) for r in rows if r
            for m in [re.fullmatch(re.escape(prefix) + r"-(\d+)", r[0])] if m]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:03d}"


# ----------------------------------------------------------------- decision

def cmd_decision():
    folder = p("docs", "decisions")
    existing = [f for f in os.listdir(folder)] if os.path.isdir(folder) else []
    nums = [int(f[:3]) for f in existing if re.match(r"\d{3}-", f)]
    num = max([n for n in nums if n > 0], default=0) + 1

    print(c(f"\nDecision record {num:03d}", "1;34"))
    title = ask("Title (state the decision itself)", hint='e.g. "Use ROS2 Humble on all machines", not "ROS2 version"')
    status = ask_choice("Status", [("Accepted", "Accepted"), ("Proposed", "Proposed")], default="Accepted")
    related = ask("Related issues / requirement IDs", required=False, hint="e.g. #15, COMM-004 (Enter to skip)")
    supersedes = ask("Does this replace an older decision? Its number", required=False, hint="Enter to skip")
    context = ask_lines("Context: what problem forced a choice, and what constraints matter?", hint="Facts only.")

    options = []
    while True:
        n = len(options) + 1
        name = ask(f"Option {n}: name", required=False,
                   hint="Options you compared. Enter to skip" if n == 1 else "Enter to finish")
        if not name:
            break
        pros = ask_lines(f"  Pros of '{name}'", required=False, hint="Enter right away if none.")
        cons = ask_lines(f"  Cons of '{name}'", required=False)
        options.append((name, pros, cons))

    default_text = None
    if len(options) == 1:
        default_text = options[0][0]
    elif len(options) > 1:
        choice = ask_choice("Which option did you choose?", [(str(i), o[0]) for i, o in enumerate(options, 1)])
        default_text = options[int(choice) - 1][0]
    decision_text = ask("Decision in one or two sentences", default=default_text,
                        hint="Press Enter to use the option name in brackets, or type a fuller sentence."
                        if default_text else None)
    factor = ask("Deciding factor (what tipped it?)")
    consequences = ask_lines("Consequences: what gets easier, harder, what to do next, when to revisit")

    meta = [f"- **Date:** {today()}", f"- **Status:** {status}"]
    if related:
        meta.append(f"- **Related:** {related}")
    if supersedes:
        meta.append(f"- **Supersedes:** {int(supersedes):03d}")
    out = [f"# {num:03d}. {title}", ""] + meta + ["", "## Context"] + [f"- {x}" for x in context]
    if options:
        out += ["", "## Options"]
    for i, (name, pros, cons) in enumerate(options, 1):
        out.append(f"{i}. **{name}**")
        out += [f"   - Pro: {x}" for x in pros] + [f"   - Con: {x}" for x in cons]
    out += ["", "## Decision", decision_text, "", f"**Deciding factor:** {factor}",
            "", "## Consequences"] + [f"- {x}" for x in consequences]
    text = "\n".join(out) + "\n"

    path = p("docs", "decisions", f"{num:03d}-{slugify(title)}.md")
    if not confirm_write(path, text):
        return info("Nothing written.")
    write(path, text)

    if supersedes:
        old = [f for f in existing if f.startswith(f"{int(supersedes):03d}-")]
        if old:
            op = p("docs", "decisions", old[0])
            t = re.sub(r"(\*\*Status:\*\*)\s*[^\n]*", rf"\1 Superseded by {num:03d}", read(op), count=1)
            write(op, t)
        else:
            warn(f"Decision {int(supersedes):03d} not found; mark it superseded by hand.")


# ----------------------------------------------------------------- requirement

def req_prefixes():
    """Prefixes come from the '| Prefix | Subsystem |' table in docs/README.md,
    so each repo defines its own. Falls back to the defaults."""
    rows = table_rows(p("docs", "README.md"), "| Prefix | Subsystem |")
    found = [(r[0], r[1]) for r in rows if len(r) >= 2 and re.fullmatch(r"[A-Z]{2,6}", r[0])]
    return found or DEFAULT_PREFIXES

REQ_SEP = "|---|---|---|---|---|---|"

def _section_prefix(line):
    m = re.match(r"##\s+([A-Z]{2,6})\b", line)
    return m.group(1) if m else None

def req_is_sectioned(lines):
    """True if every requirements table sits directly under a '## PREFIX' heading."""
    for h, _ in find_tables(lines, REQ_HEADER):
        k = h - 1
        while k >= 0 and not lines[k].strip():
            k -= 1
        if k < 0 or not _section_prefix(lines[k]):
            return False
    return True

def regroup_requirements(text):
    """Rebuild requirements.md as one section per subsystem, in the order of
    the prefix table in docs/README.md. Keeps the intro text above the first
    table and any text after the last one."""
    lines = text.splitlines()
    tables = find_tables(lines, REQ_HEADER)
    if not tables:
        return text
    intro = lines[:tables[0][0]]
    # drop blank lines and a section heading sitting right above the first table
    while intro and (not intro[-1].strip() or _section_prefix(intro[-1])):
        intro.pop()
    tail = lines[tables[-1][1]:]
    rows = [split_row(l) for h, e in tables for l in lines[h + 2:e]]
    order = req_prefixes()
    names = dict(order)
    def pre(r):
        return r[0].split("-")[0] if r and "-" in r[0] else "OTHER"
    used = []
    for k, _ in order:
        if any(pre(r) == k for r in rows):
            used.append(k)
    for r in rows:
        if pre(r) not in used:
            used.append(pre(r))
    out = intro[:]
    for k in used:
        group = sorted([r for r in rows if pre(r) == k],
                       key=lambda r: int(r[0].split("-")[1]) if r[0].split("-")[-1].isdigit() else 0)
        title = f"## {k}: {names[k]}" if k in names else f"## {k}"
        out += ["", title, "", REQ_HEADER, REQ_SEP] + [join_row(r) for r in group]
    while tail and not tail[0].strip():
        tail.pop(0)
    if tail:
        out += [""] + tail
    return "\n".join(out) + "\n"

def insert_requirement(text, prefix, cells):
    """Add a row at the end of its subsystem's section, creating the section
    (in README prefix order) if it does not exist yet."""
    lines = text.splitlines()
    names = dict(req_prefixes())
    order = [k for k, _ in req_prefixes()]
    head = next((i for i, l in enumerate(lines) if _section_prefix(l) == prefix), None)
    if head is not None:
        t = next(((h, e) for h, e in find_tables(lines, REQ_HEADER) if h > head), None)
        if t:
            lines.insert(t[1], join_row(cells))
            return "\n".join(lines) + "\n"
    title = f"## {prefix}: {names[prefix]}" if prefix in names else f"## {prefix}"
    block = [title, "", REQ_HEADER, REQ_SEP, join_row(cells), ""]
    rank = order.index(prefix) if prefix in order else len(order)
    at = None
    for i, l in enumerate(lines):
        p2 = _section_prefix(l)
        if p2 and (order.index(p2) if p2 in order else len(order)) > rank:
            at = i
            break
    if at is None:
        # after the last requirements table (before any trailing notes)
        tables = find_tables(lines, REQ_HEADER)
        at = tables[-1][1] if tables else len(lines)
        block = [""] + block[:-1]
    lines[at:at] = block
    return "\n".join(lines).rstrip() + "\n"

def load_requirements(path):
    """Read requirements.md, regrouping an old single-table file into sections."""
    if not os.path.exists(path):
        return "# Requirements\n"
    text = read(path)
    if find_tables(text.splitlines(), REQ_HEADER) and not req_is_sectioned(text.splitlines()):
        info("Reorganising requirements.md into one section per subsystem.")
        text = regroup_requirements(text)
    return text

def cmd_req():
    path = p("docs", "requirements.md")
    rows = table_rows(path, REQ_HEADER)
    prefix = ask_choice("\nSubsystem", req_prefixes())
    rid = next_id(rows, prefix)
    print(c(f"New requirement {rid}", "1;34"))

    while True:
        shall = ask("Requirement", hint='Form: "The <thing> shall <do what> <measurable limit>."')
        problems = []
        if "shall" not in shall.lower():
            problems.append('no "shall"')
        if not re.search(r"\d", shall):
            problems.append("no number to measure")
        if not problems or yes(f"Warning: {', '.join(problems)}. Keep it anyway?"):
            break
    rationale = ask("Rationale (why it matters)")
    method = ask_choice("How will you verify it?", METHODS, default="T")
    status = ask_choice("Status", [("Draft", "Draft"), ("Approved", "Approved")], default="Draft")

    cells = [rid, cell(shall), cell(rationale), method, status, ""]
    text = insert_requirement(load_requirements(path), prefix, cells)
    if not confirm_write(path, join_row(cells)):
        return info("Nothing written.")
    write(path, text)


def cmd_test(rid=None):
    path = p("docs", "requirements.md")
    rows = table_rows(path, REQ_HEADER)
    if not rows:
        sys.exit("No requirements found in docs/requirements.md.")
    if not rid:
        active = [r for r in rows if len(r) >= 5 and r[4] != "Deleted"]
        active.sort(key=lambda r: r[4] == "Verified")      # untested first
        rid = ask_choice("Which requirement did you test?",
                         [(r[0], f"{r[4]:<9} {_short(r[1], 70)}") for r in active],
                         details=[_req_detail(r) for r in active])
    rid = rid.upper()
    match = [r for r in rows if r[0] == rid]
    if not match:
        sys.exit(f"{rid} not found in requirements.md.")
    row = match[0] + [""] * (6 - len(match[0]))
    print(c(f"\n{rid}: {row[1]}", "1;34"))

    result = ask_choice("Result", [("Verified", "Passed"), ("Failed", "Failed")])
    measured = ask("What did you measure / observe?", hint='e.g. "stop at 5.2 s, 3 runs"')
    evidence = ask("Evidence (file in media/, log name, plot)", required=False)
    date = ask("Test date", default=today())
    entry = f"{date}: {measured}" + (f". {evidence}" if evidence else "")
    row[4] = result
    row[5] = cell(entry) if not row[5] else row[5] + "<br>" + cell(entry)

    lines = load_requirements(path).splitlines()
    for h, e in find_tables(lines, REQ_HEADER):
        for i in range(h + 2, e):
            if split_row(lines[i])[0] == rid:
                lines[i] = join_row(row)
    if not confirm_write(path, join_row(row)):
        return info("Nothing written.")
    write(path, "\n".join(lines) + "\n")
    if result == "Failed":
        warn("Failed test: consider a fault-table row (doc fault) or a new issue.")


# ----------------------------------------------------------------- fault table

def check_req_link(rid):
    """Warn if a fault row links to a requirement that is missing or deleted."""
    status = {r[0]: (r[4] if len(r) > 4 else "") for r in table_rows(p("docs", "requirements.md"), REQ_HEADER)}
    rid = rid.upper()
    if rid not in status:
        warn(f"{rid} is not in requirements.md yet. Add it with: doc req")
    elif status[rid] == "Deleted":
        warn(f"{rid} is marked Deleted. Link a requirement that is still active.")

def cmd_fault():
    path = p("docs", "fdir.md")
    rows = table_rows(path, FDIR_HEADER)
    fid = next_id(rows, "FM")
    print(c(f"\nNew failure mode {fid}", "1;34"))
    failure = ask("What fails?", hint='e.g. "Radio link lost"')
    effect = ask("Effect on the system / mission")
    detection = ask("How is it detected?", hint='e.g. "no heartbeat ACK for 5 s"')
    response = ask("Immediate response (isolate / make safe)")
    recovery = ask("Recovery", hint='e.g. "resume when link returns; operator re-arms"')
    sev = ask_choice("Severity", SEVERITY)
    req = ask("Requirement that covers it (ID)", required=False, hint="Enter to skip")
    if req:
        check_req_link(req)
    cells = [fid] + [cell(x) for x in (failure, effect, detection, response, recovery)] + [sev, req.upper()]
    base = read(path) if os.path.exists(path) else "# Fault table (FDIR / FMEA)\n"
    if not confirm_write(path, join_row(cells)):
        return info("Nothing written.")
    write(path, insert_row(base, FDIR_HEADER, cells))


# ----------------------------------------------------------------- update

CHANGE_HEADER = "| Date | ID | Change |"
DEC_STATUSES = [("Proposed", "Proposed"), ("Accepted", "Accepted"),
                ("Rejected", "Rejected"), ("Superseded", "Superseded by a newer decision")]
REQ_STATUSES = [("Draft", "Draft"), ("Approved", "Approved"), ("Verified", "Verified"),
                ("Failed", "Failed"), ("Deleted", "Deleted (dropped; the ID is never reused)")]

def _short(text, n=60):
    text = text.replace("\\|", "|")
    return text if len(text) <= n else text[:n - 3] + "..."

def _replace_row(lines, header, rid, new_cells):
    for h, e in find_tables(lines, header):
        for i in range(h + 2, e):
            if split_row(lines[i])[0] == rid:
                lines[i] = join_row(new_cells)
                return True
    return False

def _decisions():
    folder = p("docs", "decisions")
    out = []
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            m = re.match(r"(\d{3})-", f)
            if m and int(m.group(1)) > 0:
                text = read(os.path.join(folder, f))
                title = re.search(r"^#\s*\d+\.\s*(.*)$", text, re.M)
                status = re.search(r"\*\*Status:\*\*\s*(.*)$", text, re.M)
                out.append((m.group(1), f, title.group(1) if title else f,
                            status.group(1).strip() if status else ""))
    return out

def _plain(text):
    return text.replace("\\|", "|")

def _req_detail(r):
    r = r + [""] * (6 - len(r))
    method = dict(METHODS).get(r[3], r[3])
    ev = [e.strip() for e in _plain(r[5]).split("<br>") if e.strip()]
    return "\n".join([f"{r[0]} · {r[4] or 'no status'}", _plain(r[1]), f"Rationale: {_plain(r[2]) or '-'}",
                      f"Verified by: {method or '-'}", "Evidence:" if ev else "Evidence: none yet"] + [f"  {e}" for e in ev])

def _fault_detail(f):
    f = f + [""] * (8 - len(f))
    names = ["Failure", "Effect", "Detection", "Response", "Recovery"]
    return "\n".join([f"{f[0]} · severity {f[6] or '?'} · requirement {f[7] or 'none'}"] +
                     [f"{n}: {_plain(f[i]) or '-'}" for i, n in enumerate(names, 1)])

def _decision_detail(d):
    text = read(p("docs", "decisions", d[1]))
    related = re.search(r"\*\*Related:\*\*\s*(.*)$", text, re.M)
    body = re.search(r"^## Decision\s*\n(.*?)(?:\n## |\Z)", text, re.S | re.M)
    lines = [f"{d[0]}. {d[2]}", f"Status: {d[3] or '-'}"]
    if related:
        lines.append(f"Related: {related.group(1).strip()}")
    if body:
        lines += [l for l in body.group(1).strip().splitlines() if l.strip()]
    return "\n".join(lines)

def update_decision(num=None):
    decs = _decisions()
    if not decs:
        sys.exit("No decision records yet.")
    if not num:
        num = ask_choice("Which decision?", [(d[0], f"{d[3]:<22} {_short(d[2], 60)}") for d in decs],
                         details=[_decision_detail(d) for d in decs])
    num = num.zfill(3)
    match = [d for d in decs if d[0] == num]
    if not match:
        sys.exit(f"No decision {num}.")
    n, fname, title, status = match[0]
    path = p("docs", "decisions", fname)
    print(c(f"\n{n}. {title}", "1;34"))
    rel_now = re.search(r"\*\*Related:\*\*\s*(.*)$", read(path), re.M)
    field = ask_choice("Which field?", [("status", f"Status [{status}]"), ("related", "Related issues / requirement IDs")],
                       details=[f"Status\n{status or '-'}", f"Related\n{rel_now.group(1).strip() if rel_now else '(none)'}"])
    text = read(path)
    if field == "status":
        new = ask_choice("New status", DEC_STATUSES)
        if new == "Superseded":
            by = ask("Superseded by decision number")
            new = f"Superseded by {by.zfill(3)}"
        text = re.sub(r"(\*\*Status:\*\*)[^\n]*", lambda m: f"{m.group(1)} {new}", text, count=1)
        preview = f"Status: {status}  ->  {new}"
    else:
        old = re.search(r"\*\*Related:\*\*\s*(.*)$", text, re.M)
        old_val = old.group(1).strip() if old else ""
        new = ask("Related issues / requirement IDs", default=old_val or None,
                  hint="Replaces the current value. e.g. #3, NAV-001")
        if old:
            text = re.sub(r"(\*\*Related:\*\*)[^\n]*", lambda m: f"{m.group(1)} {new}", text, count=1)
        else:
            text = re.sub(r"(- \*\*Status:\*\*[^\n]*\n)", lambda m: m.group(1) + f"- **Related:** {new}\n", text, count=1)
        preview = f"Related: {old_val or '(none)'}  ->  {new}"
    if not confirm_write(path, preview):
        return info("Nothing written.")
    write(path, text)

def update_requirement(rid=None):
    path = p("docs", "requirements.md")
    rows = table_rows(path, REQ_HEADER)
    if not rows:
        sys.exit("No requirements yet.")
    if not rid:
        rid = ask_choice("Which requirement?", [(r[0], f"{(r[4] if len(r) > 4 else ''):<9} {_short(r[1], 70)}") for r in rows],
                         details=[_req_detail(r) for r in rows])
    rid = rid.upper()
    match = [r for r in rows if r[0] == rid]
    if not match:
        sys.exit(f"{rid} not found in requirements.md.")
    row = match[0] + [""] * (6 - len(match[0]))
    print(c(f"\n{rid}: {row[1]}", "1;34"))
    field = ask_choice("Which field?", [("status", f"Status [{row[4]}]"), ("text", "Requirement text"),
                                        ("rationale", "Rationale"), ("method", f"Verification method [{row[3]}]")],
                       details=[f"Status now\n{row[4] or '-'}", f"Requirement now\n{_plain(row[1])}",
                                f"Rationale now\n{_plain(row[2]) or '-'}",
                                f"Verification method now\n{dict(METHODS).get(row[3], row[3]) or '-'}"])
    new = list(row)
    if field == "status":
        val = ask_choice("New status", REQ_STATUSES)
        new[4] = val
        change = f"Status: {row[4]} -> {val}"
        if val == "Deleted":
            why = ask("Why is it dropped?")
            change += f" ({why})"
        elif val in ("Verified", "Failed"):
            info("  Tip: doc test records the result together with its evidence.")
    elif field == "text":
        while True:
            val = ask("Requirement", default=row[1].replace("\\|", "|"),
                      hint='Press Enter to keep it. Form: "The <thing> shall <do what> <measurable limit>."')
            problems = []
            if "shall" not in val.lower():
                problems.append('no "shall"')
            if not re.search(r"\d", val):
                problems.append("no number to measure")
            if not problems or yes(f"Warning: {', '.join(problems)}. Keep it anyway?"):
                break
        new[1] = cell(val)
        change = f'Requirement: was "{row[1]}"'
        if row[4] == "Verified":
            warn("This requirement was Verified. Changing it usually means it must be tested again.")
            if yes("Set its status back to Approved?", default=True):
                new[4] = "Approved"
                change += "; status Verified -> Approved (retest needed)"
    elif field == "rationale":
        val = ask("Rationale", default=row[2].replace("\\|", "|"))
        new[2] = cell(val)
        change = f'Rationale: was "{row[2]}"'
    else:
        val = ask_choice("Verification method", METHODS, default=row[3] or "T")
        new[3] = val
        change = f"Method: {row[3]} -> {val}"
    if new == row:
        return info("No change.")
    lines = load_requirements(path).splitlines()
    _replace_row(lines, REQ_HEADER, rid, new)
    text = "\n".join(lines) + "\n"
    if not any(l.strip() == "## Change log" for l in lines):
        text = text.rstrip() + "\n\n## Change log\n\n" + CHANGE_HEADER + "\n|---|---|---|\n"
    text = insert_row(text, CHANGE_HEADER, [today(), rid, cell(change)])
    if not confirm_write(path, f"before: {join_row(row)}\nafter:  {join_row(new)}\nlog:    {change}"):
        return info("Nothing written.")
    write(path, text)

def update_fault(fid=None):
    path = p("docs", "fdir.md")
    rows = table_rows(path, FDIR_HEADER)
    if not rows:
        sys.exit("No fault table rows yet.")
    if not fid:
        fid = ask_choice("Which failure mode?", [(r[0], f"sev {r[6] if len(r) > 6 else '?'}  req {(r[7] if len(r) > 7 else '') or '-':<9} {_short(r[1], 60)}") for r in rows],
                         details=[_fault_detail(r) for r in rows])
    fid = fid.upper()
    match = [r for r in rows if r[0] == fid]
    if not match:
        sys.exit(f"{fid} not found in fdir.md.")
    row = match[0] + [""] * (8 - len(match[0]))
    print(c(f"\n{fid}: {row[1]}", "1;34"))
    names = ["Failure", "Effect", "Detection", "Response", "Recovery", "Severity", "Requirement"]
    opts = [(str(i), f"{n} [{_short(row[i], 40) or '-'}]") for i, n in enumerate(names, 1)]
    col = int(ask_choice("Which field?", opts,
                         details=[f"{n} now\n{_plain(row[i]) or '-'}" for i, n in enumerate(names, 1)]))
    new = list(row)
    if col == 6:
        new[6] = ask_choice("Severity", SEVERITY)
    elif col == 7:
        val = ask("Requirement that covers it (ID)", required=False, default=row[7] or None)
        if val:
            check_req_link(val)
        new[7] = val.upper()
    else:
        new[col] = cell(ask(names[col - 1], default=row[col].replace("\\|", "|") or None))
    if new == row:
        return info("No change.")
    lines = read(path).splitlines()
    _replace_row(lines, FDIR_HEADER, fid, new)
    if not confirm_write(path, f"before: {join_row(row)}\nafter:  {join_row(new)}"):
        return info("Nothing written.")
    write(path, "\n".join(lines) + "\n")

def cmd_update(target=None):
    """Change something written earlier: a status, a text, a link."""
    if target:
        t = target.strip()
        if re.fullmatch(r"\d{1,3}", t):
            return update_decision(t)
        if re.fullmatch(r"FM-\d+", t, re.I):
            return update_fault(t.upper())
        return update_requirement(t.upper())
    kind = ask_choice("\nWhat do you want to update?", [
        ("decision", "Decision record (status, related)"),
        ("req", "Requirement (status, text, rationale, method)"),
        ("fault", "Fault table row (any column, e.g. the linked requirement)")])
    {"decision": update_decision, "req": update_requirement, "fault": update_fault}[kind]()


# ----------------------------------------------------------------- procedure

def cmd_procedure():
    print(c("\nNew procedure", "1;34"))
    title = ask("What is this the procedure for?", hint='e.g. "mounting a motor thermistor"')
    path = p("docs", "procedures", slugify(title).replace("-", "_") + ".md")
    if os.path.exists(path):
        sys.exit(f"{rel(path)} already exists. Edit it directly.")
    applies = ask("Applies to (part / requirement)", required=False)
    duration = ask("Rough time it takes", required=False)
    needs = ask_lines("Tools and parts needed", required=False)
    steps = ask_lines("Steps, in order", hint="Write each step as an action.")
    warnings = ask_lines("Warnings (things that break if skipped)", required=False)
    photo = ask("Photo in docs/media/ (file name)", required=False)

    out = [f"# Procedure: {title}", ""]
    if applies:
        out.append(f"- **Applies to:** {applies}")
    if duration:
        out.append(f"- **Time:** {duration}")
    out.append(f"- **Last updated:** {today()}")
    if needs:
        out += ["", "## You need"] + [f"- {x}" for x in needs]
    out += ["", "## Steps"] + [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    for w in warnings:
        out += ["", f"> **Warning:** {w}"]
    if photo:
        out += ["", "## Photos", f"`media/{photo}`"]
    text = "\n".join(out) + "\n"
    if not confirm_write(path, text):
        return info("Nothing written.")
    write(path, text)


# ----------------------------------------------------------------- checklist

def cmd_check():
    path = p("docs", "procedures", "pre_power_checklist.md")
    text = read(path) if os.path.exists(path) else "# Pre-power checklist\n\n## Checks\n\n## History\n| Date | Line added | Why |\n|---|---|---|\n"
    lines = text.splitlines()
    sections = [l[3:].strip() for l in lines if l.startswith("## ") and l[3:].strip() != "History"]
    print(c("\nNew checklist line", "1;34"))
    item = ask("The check, as something you can tick", hint='e.g. "All terminal block wires have ferrules (tug test)"')
    why = ask("Why it was added (what broke or nearly broke)")
    opts = [(s, s) for s in sections] + [("+ new section", "+ new section")]
    sec = ask_choice("Which section?", opts)
    if sec == "+ new section":
        sec = ask("New section name")
        h = next((i for i, l in enumerate(lines) if l.strip() == "## History"), len(lines))
        lines[h:h] = [f"## {sec}", f"- [ ] {item}", ""]
    else:
        i = next(i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip() == sec) + 1
        last = i
        while i < len(lines) and not lines[i].startswith("## "):
            if lines[i].startswith("- [") or (lines[i].startswith("  ") and last == i - 1 and lines[i].strip()):
                last = i
            i += 1
        lines.insert(last + 1, f"- [ ] {item}")
    if not any(l.strip() == "## History" for l in lines):
        lines += ["", "## History"]
    new = insert_row("\n".join(lines), HIST_HEADER, [today(), cell(item), cell(why)])
    if not confirm_write(path, f"## {sec}\n- [ ] {item}\n\nHistory: {today()} | {item} | {why}"):
        return info("Nothing written.")
    write(path, new)


# ----------------------------------------------------------------- devlog

LOG_SECTIONS = [("**Done**", "Done this week"), ("**Broke / learned**", "What broke or what you learned"),
                ("**Next**", "Next steps"), ("**Media**", "Photos / videos saved (file names)")]

def cmd_log():
    path = p("docs", "devlog.md")
    d = datetime.date.today()
    monday = (d - datetime.timedelta(days=d.weekday())).isoformat()
    heading = f"## Week of {monday}"
    print(c(f"\nDevlog: {heading[3:]}", "1;34"))
    answers = {}
    for label, prompt in LOG_SECTIONS:
        answers[label] = ask_lines(prompt, required=label == "**Done**")

    text = read(path) if os.path.exists(path) else "# Devlog\n\nNewest entry at the top.\n\n---\n"
    lines = text.splitlines()
    if heading in lines:
        start = lines.index(heading) + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ") or lines[i].strip() == "---"), len(lines))
        block = lines[start:end]
        for label, _ in LOG_SECTIONS:
            items = [f"- {x}" for x in answers[label]]
            if not items:
                continue
            if label in block:
                i = block.index(label) + 1
                while i < len(block) and block[i].startswith("- "):
                    i += 1
                block[i:i] = items
            else:
                while block and not block[-1].strip():
                    block.pop()
                block += ["", label] + items
        while block and not block[-1].strip():
            block.pop()
        lines[start:end] = block + [""]
        preview = "(added to the existing entry)\n" + "\n".join(
            f"{l}\n" + "\n".join(f"- {x}" for x in answers[l]) for l, _ in LOG_SECTIONS if answers[l])
    else:
        entry = [heading, ""]
        for label, _ in LOG_SECTIONS:
            if answers[label]:
                entry += [label] + [f"- {x}" for x in answers[label]] + [""]
        entry.append("---")
        sep = next((i for i, l in enumerate(lines) if l.strip() == "---"), None)
        at = sep + 1 if sep is not None else len(lines)
        lines[at:at] = [""] + entry
        preview = "\n".join(entry)
    if not confirm_write(path, preview):
        return info("Nothing written.")
    write(path, "\n".join(lines).rstrip() + "\n")


# ----------------------------------------------------------------- menu + hook

MENU = [
    ("idea", "I got an idea"),
    ("bug", "Something behaves wrong (bug)"),
    ("decision", "I chose between options"),
    ("req", "I committed to building something"),
    ("fault", "I asked 'what if this breaks?'"),
    ("test", "I tested a requirement"),
    ("procedure", "I assembled / set up something with steps"),
    ("check", "Something broke or nearly broke"),
    ("update", "Something I wrote earlier changed"),
    ("log", "End of the week"),
    ("report", "Show me the project status"),
]

# ----------------------------------------------------------------- GitHub issues

DEFAULT_SUBSYSTEMS = ["comms", "power", "motors", "sensors", "software", "mech", "fdir", "other"]

def subsystems():
    """Subsystem list from the repo's issue form, so the CLI and web form match."""
    path = p(".github", "ISSUE_TEMPLATE", "idea.yml")
    if os.path.exists(path):
        m = re.search(r"id:\s*subsystem.*?options:\s*\[([^\]]*)\]", read(path), re.S)
        if m:
            items = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
            if items:
                return items
    return DEFAULT_SUBSYSTEMS

def gh_ready():
    """True if the GitHub CLI is installed and logged in; explains how otherwise."""
    if not shutil.which("gh"):
        warn("GitHub CLI (gh) is not installed. Install and log in once:")
        print("    brew install gh\n    gh auth login")
        return False
    r = subprocess.run(["gh", "auth", "status"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        warn("GitHub CLI is not logged in. Run once:  gh auth login")
        return False
    return True

def ensure_labels(labels):
    """Create any labels that do not exist on GitHub yet (gh refuses unknown labels)."""
    r = subprocess.run(["gh", "label", "list", "--limit", "500", "--json", "name", "-q", ".[].name"],
                       cwd=ROOT, capture_output=True, text=True)
    existing = set(r.stdout.split("\n")) if r.returncode == 0 else set()
    for label in labels:
        if label not in existing:
            subprocess.run(["gh", "label", "create", label], cwd=ROOT, capture_output=True, text=True)
            info(f"  created label '{label}' on GitHub")

def section(title, lines):
    body = "\n".join(lines) if lines else "_No response_"
    return f"### {title}\n\n{body}\n"

def create_issue(title, body, labels):
    preview("new GitHub issue", f"Title:  {title}\nLabels: {', '.join(labels)}\n\n{body}")
    if not save_menu("Create this issue on GitHub?", "Create it"):
        return info("Nothing created.")
    ensure_labels(labels)
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels:
        cmd += ["--label", label]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        warn("GitHub refused the issue:")
        print(r.stderr.strip())
        return
    url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    num = url.rstrip("/").rsplit("/", 1)[-1]
    ok(f"Created #{num}: {url}")
    info(f"  Refer to it as #{num} in decisions, requirements and commits (e.g. 'fixes #{num}').")

def cmd_idea():
    if not gh_ready():
        return
    print(c("\nNew idea (GitHub issue)", "1;34"))
    title = ask("Title", hint='Short, e.g. "Heartbeat with failsafe stop"')
    what = ask_lines("What: the idea in one or two sentences")
    why = ask_lines("Why: what problem it solves or what it enables")
    sub = ask_choice("Subsystem", [(x, x) for x in subsystems()])
    prio = ask_choice("Priority", [("must", "must"), ("should", "should"), ("could", "could")], default="should")
    questions = ask_lines("Open questions", required=False, hint="Enter right away if none.")
    body = "\n".join([section("What", what), section("Why", why), section("Subsystem", [sub]),
                      section("Priority", [prio]), section("Open questions", [f"- {q}" for q in questions])])
    create_issue(title, body, ["idea", sub, prio])

def cmd_bug():
    if not gh_ready():
        return
    print(c("\nNew bug / fault (GitHub issue)", "1;34"))
    title = ask("Title", hint='Short, e.g. "Robot keeps driving after radio link is lost"')
    happened = ask_lines("What happened")
    expected = ask_lines("What should have happened", hint="Mention the requirement ID if there is one.")
    steps = ask_lines("Steps to reproduce", required=False)
    sub = ask_choice("Subsystem", [(x, x) for x in subsystems()])
    try:
        ver = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    except OSError:
        ver = ""
    firmware = ask("Firmware version / commit", required=False, default=ver or None)
    evidence = ask_lines("Logs, photos, videos (file names)", required=False)
    body = "\n".join([section("What happened", happened), section("What should have happened", expected),
                      section("Steps to reproduce", [f"{i}. {s}" for i, s in enumerate(steps, 1)]),
                      section("Subsystem", [sub]), section("Firmware version / commit", [firmware] if firmware else []),
                      section("Logs, photos, videos", [f"- {e}" for e in evidence])])
    create_issue(title, body, ["bug", sub])

COMMANDS = {"decision": cmd_decision, "req": cmd_req, "test": cmd_test, "fault": cmd_fault,
            "procedure": cmd_procedure, "check": cmd_check, "log": cmd_log, "idea": cmd_idea,
            "bug": cmd_bug, "update": cmd_update, "report": lambda: cmd_report([])}

def cmd_menu():
    key = ask_choice("What just happened?", [(k, v) for k, v in MENU])
    COMMANDS[key]()

def cmd_hook():
    """Called by the git post-commit hook."""
    try:
        msg = subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=ROOT,
                             capture_output=True, text=True).stdout
    except OSError:
        return
    issues = re.findall(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", msg, re.I)
    if not issues:
        return
    print(c(f"\nThis commit closes #{', #'.join(issues)}. Did it create a document?", "1;34"))

    def flow():
        key = ask_choice("", [("decision", "Decision"), ("req", "Requirement"), ("test", "Test result"),
                              ("procedure", "Procedure"), ("fault", "Fault row"), ("no", "Nothing")], default="no")
        if key != "no":
            COMMANDS[key]()
    run_with_back(flow)

HOOK = """#!/bin/sh
# Installed by tools/doc.py: after a commit that closes an issue,
# ask whether it created a document. Skipped when there is no terminal.
( exec < /dev/tty ) 2>/dev/null || exit 0
exec < /dev/tty
python3 "$(git rev-parse --show-toplevel)/tools/doc.py" hook || true
"""

def cmd_install_hook():
    gitdir = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if not gitdir:
        sys.exit("Not a git repository.")
    hook = os.path.join(ROOT, gitdir, "hooks", "post-commit")
    if os.path.exists(hook) and "tools/doc.py" not in read(hook):
        sys.exit(f"{hook} already exists and was not made by doc.py. Merge it by hand.")
    os.makedirs(os.path.dirname(hook), exist_ok=True)
    with open(hook, "w") as f:
        f.write(HOOK)
    os.chmod(hook, 0o755)
    ok("Installed post-commit hook. It runs after commits containing 'fixes #N' / 'closes #N'.")



# ----------------------------------------------------------------- report

REPORT_CSS = """
:root{--bg:#fafafa;--surface:#ffffff;--ink:#0b0b0b;--muted:#5c5c5c;--hair:#e7e7e7;--ring:rgba(11,11,11,.10);
--good:#0aac23;--good-ink:#006c10;--crit:#dc3c3d;--crit-ink:#b42324;--appr:#8a8a8a;--draft:#c9c9c9;--warn:#fbb315;--accent:#2a62d4}
@media (prefers-color-scheme:dark){:root{--bg:#111;--surface:#191919;--ink:#f2f2f2;--muted:#a8a8a8;--hair:#303030;--ring:rgba(255,255,255,.10);
--good:#0aac23;--good-ink:#53c556;--crit:#dc3c3d;--crit-ink:#ff7a7a;--appr:#8f8f8f;--draft:#4d4d4d;--warn:#fbb315;--accent:#7aa2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 24px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:40px 0 12px}
h3{font-size:15px;margin:22px 0 8px}.sub{color:var(--muted);font-size:13px}a{color:var(--accent)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:24px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px}
.tile .n{font-size:28px;font-weight:600;font-variant-numeric:tabular-nums}.tile .l{color:var(--muted);font-size:13px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px 18px}
.bars{display:grid;grid-template-columns:minmax(140px,220px) 1fr 140px;gap:10px 14px;align-items:center}
.bar{display:flex;gap:2px;height:14px}.bar span{display:block;height:100%}.bar span:first-child{border-radius:4px 0 0 4px}
.bar span:last-child{border-radius:0 4px 4px 0}.bar span:only-child{border-radius:4px}.cnt{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;font-size:13px;color:var(--muted)}.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--hair);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:12.5px}td.id{white-space:nowrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
.pill{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-size:12.5px;font-weight:600}
.pill i{font-style:normal;display:inline-grid;place-items:center;width:16px;height:16px;border-radius:50%;font-size:10.5px;color:#fff}
.Verified{color:var(--good-ink)}.Verified i{background:var(--good)}.Failed{color:var(--crit-ink)}.Failed i{background:var(--crit)}
.Approved{color:var(--muted)}.Approved i{background:var(--appr)}.Draft{color:var(--muted)}.Draft i{background:transparent;border:1.5px solid var(--appr);color:var(--appr)}
.Deleted{color:var(--muted);text-decoration:line-through}.Deleted i{background:transparent;color:var(--muted)}
.att li{margin:4px 0}.att .why{color:var(--muted)}.empty{color:var(--muted);font-style:italic}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:760px){.two{grid-template-columns:1fr}.bars{grid-template-columns:1fr}}
.dev h3{margin-top:0}.dev ul{margin:4px 0 10px;padding-left:20px}code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
footer{margin-top:48px;color:var(--muted);font-size:12px}
"""

PILL_ICON = {"Verified": "✓", "Failed": "✕", "Approved": "●", "Draft": "", "Deleted": "–"}

def _h(text):
    """Escape a markdown cell for HTML, keeping <br> line breaks and `code`."""
    t = html.escape(text.replace("\\|", "|"))
    t = t.replace("&lt;br&gt;", "<br>")
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)

def _pill(status):
    return f'<span class="pill {html.escape(status)}"><i>{PILL_ICON.get(status, "?")}</i>{html.escape(status or "-")}</span>'

def _git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""

def _open_issues():
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "200", "--json",
                            "number,title,labels,url"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        import json
        return json.loads(r.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None

def _latest_devlog():
    path = p("docs", "devlog.md")
    if not os.path.exists(path):
        return None, []
    lines = read(path).splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("## ")), None)
    if start is None:
        return None, []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ") or lines[i].strip() == "---"), len(lines))
    return lines[start][3:].strip(), lines[start + 1:end]

def build_report(with_issues=True):
    readme = p("docs", "README.md")
    m = re.search(r"^#\s+(.*?)\s+documentation\s*$", read(readme), re.M) if os.path.exists(readme) else None
    project = m.group(1) if m else os.path.basename(ROOT)
    names = dict(req_prefixes())
    order = [k for k, _ in req_prefixes()]

    reqs = [r + [""] * (6 - len(r)) for r in table_rows(p("docs", "requirements.md"), REQ_HEADER)]
    live = [r for r in reqs if r[4] != "Deleted"]
    req_status = {r[0]: r[4] for r in reqs}
    faults = [r + [""] * (8 - len(r)) for r in table_rows(p("docs", "fdir.md"), FDIR_HEADER)]
    decisions = _decisions()
    changes = table_rows(p("docs", "requirements.md"), CHANGE_HEADER)
    issues = _open_issues() if with_issues else None

    verified = sum(r[4] == "Verified" for r in live)
    failed = [r for r in live if r[4] == "Failed"]
    unproven = [r for r in live if r[4] in ("Draft", "Approved")]
    uncovered = [f for f in faults if not f[7]]
    bad_links = [f for f in faults if f[7] and req_status.get(f[7].upper()) in (None, "Deleted")]
    proposed = [d for d in decisions if d[3].startswith("Proposed")]

    def prefix(r):
        return r[0].split("-")[0]
    groups = []
    for k in order + sorted({prefix(r) for r in reqs} - set(order)):
        rows = [r for r in reqs if prefix(r) == k]
        if rows:
            groups.append((k, names.get(k, k), rows))

    out = []
    w = out.append
    w(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>")
    w(f"<title>{html.escape(project)} status</title><style>{REPORT_CSS}</style></head><body><main>")
    commit = _git("log", "-1", "--format=%h · %cs")
    w(f"<h1>{html.escape(project)}</h1><div class='sub'>Status report generated {datetime.datetime.now():%Y-%m-%d %H:%M}"
      + (f" · last commit {html.escape(commit)}" if commit else "") + " · by doc-kit</div>")

    pct = f"{round(100 * verified / len(live))}%" if live else "-"
    tiles = [(f"{verified}/{len(live)}", f"requirements verified ({pct})"),
             (str(len(failed)), "requirements failed"),
             (str(len(unproven)), "requirements not yet tested"),
             (str(len(uncovered) + len(bad_links)), "failure modes without an active requirement"),
             (str(len(proposed)), "decisions still proposed")]
    if issues is not None:
        tiles.append((str(len(issues)), "open GitHub issues"))
    w("<div class='tiles'>" + "".join(f"<div class='tile'><div class='n'>{n}</div><div class='l'>{l}</div></div>" for n, l in tiles) + "</div>")

    # attention list
    w("<h2>Needs attention</h2><div class='card att'>")
    items = []
    for r in failed:
        items.append(f"<li>{_pill('Failed')} <b>{r[0]}</b> {_h(r[1])} <span class='why'>· failed its last test</span></li>")
    for f in uncovered:
        items.append(f"<li><b>{f[0]}</b> {_h(f[1])} <span class='why'>· no requirement promises this failure is handled</span></li>")
    for f in bad_links:
        items.append(f"<li><b>{f[0]}</b> {_h(f[1])} <span class='why'>· linked to {html.escape(f[7])}, which is {'deleted' if req_status.get(f[7].upper()) == 'Deleted' else 'missing'}</span></li>")
    for d in proposed:
        items.append(f"<li><b>Decision {d[0]}</b> {_h(d[2])} <span class='why'>· still proposed</span></li>")
    for r in unproven:
        items.append(f"<li>{_pill(r[4])} <b>{r[0]}</b> {_h(r[1])} <span class='why'>· no passing test yet</span></li>")
    w("<ul>" + "".join(items) + "</ul>" if items else "<div class='empty'>Nothing. Every requirement is verified and every failure mode is covered.</div>")
    w("</div>")

    # requirements by subsystem: one segmented bar per subsystem
    seg = [("Verified", "var(--good)"), ("Failed", "var(--crit)"), ("Approved", "var(--appr)"), ("Draft", "var(--draft)")]
    w("<h2>Requirements by subsystem</h2><div class='card'>")
    if groups:
        w("<div class='bars'>")
        for k, name, rows in groups:
            act = [r for r in rows if r[4] != "Deleted"]
            parts = []
            for st, col in seg:
                n = sum(r[4] == st for r in act)
                if n:
                    parts.append(f"<span style='flex:{n};background:{col}' title='{st}: {n} of {len(act)}'></span>")
            v = sum(r[4] == "Verified" for r in act)
            w(f"<div><b>{html.escape(k)}</b> <span class='sub'>{html.escape(name)}</span></div>"
              f"<div class='bar'>{''.join(parts) or ''}</div><div class='cnt'>{v} of {len(act)} verified</div>")
        w("</div><div class='legend'>" + "".join(f"<span><span class='sw' style='background:{col}'></span>{st}</span>" for st, col in seg) + "</div>")
    else:
        w("<div class='empty'>No requirements yet. Add one with <code>doc req</code>.</div>")
    w("</div>")

    for k, name, rows in groups:
        w(f"<h3>{html.escape(k)} · {html.escape(name)}</h3><div class='card'><table><tr><th>ID</th><th>Requirement</th><th>Status</th><th>Evidence</th></tr>")
        for r in rows:
            w(f"<tr><td class='id'>{html.escape(r[0])}</td><td>{_h(r[1])}<div class='sub'>{_h(r[2])}</div></td><td>{_pill(r[4])}</td><td>{_h(r[5]) or '<span class=empty>none yet</span>'}</td></tr>")
        w("</table></div>")

    # traceability
    w("<h2>Failure modes and their requirements</h2><div class='card'>")
    if faults:
        w("<table><tr><th>ID</th><th>Failure</th><th>Response</th><th>Sev</th><th>Requirement</th><th>Its status</th></tr>")
        for f in faults:
            st = req_status.get(f[7].upper(), "") if f[7] else ""
            link = html.escape(f[7]) if f[7] else "<span class='empty'>none</span>"
            w(f"<tr><td class='id'>{html.escape(f[0])}</td><td>{_h(f[1])}</td><td>{_h(f[4])}</td><td>{html.escape(f[6])}</td>"
              f"<td class='id'>{link}</td><td>{_pill(st) if st else ('<span class=empty>missing</span>' if f[7] else '')}</td></tr>")
        w("</table>")
    else:
        w("<div class='empty'>No failure modes yet. Add one with <code>doc fault</code>.</div>")
    w("</div>")

    # decisions + devlog
    w("<div class='two'><div><h2>Decisions</h2><div class='card'>")
    if decisions:
        w("<table><tr><th>#</th><th>Decision</th><th>Status</th></tr>")
        for d in decisions:
            w(f"<tr><td class='id'><a href='decisions/{html.escape(d[1])}'>{d[0]}</a></td><td>{_h(d[2])}</td><td>{html.escape(d[3])}</td></tr>")
        w("</table>")
    else:
        w("<div class='empty'>No decisions yet.</div>")
    w("</div></div><div><h2>Latest devlog</h2><div class='card dev'>")
    title, body = _latest_devlog()
    if title:
        w(f"<h3>{_h(title)}</h3>")
        in_list = False
        for line in body:
            if line.startswith("- "):
                if not in_list:
                    w("<ul>"); in_list = True
                w(f"<li>{_h(line[2:])}</li>")
            else:
                if in_list:
                    w("</ul>"); in_list = False
                if line.strip():
                    w(f"<div>{_h(line)}</div>")
        if in_list:
            w("</ul>")
    else:
        w("<div class='empty'>No entries yet. Add one with <code>doc log</code>.</div>")
    w("</div></div></div>")

    if changes:
        w("<h2>Recent requirement changes</h2><div class='card'><table><tr><th>Date</th><th>ID</th><th>Change</th></tr>")
        for ch in list(reversed(changes))[:10]:
            ch = ch + [""] * (3 - len(ch))
            w(f"<tr><td class='id'>{html.escape(ch[0])}</td><td class='id'>{html.escape(ch[1])}</td><td>{_h(ch[2])}</td></tr>")
        w("</table></div>")

    if issues:
        w("<h2>Open issues</h2><div class='card'><table><tr><th>#</th><th>Title</th><th>Labels</th></tr>")
        for it in issues[:30]:
            labels = ", ".join(l.get("name", "") for l in it.get("labels", []))
            w(f"<tr><td class='id'><a href='{html.escape(it.get('url', ''))}'>#{it.get('number')}</a></td><td>{html.escape(it.get('title', ''))}</td><td class='sub'>{html.escape(labels)}</td></tr>")
        w("</table></div>")

    w("<footer>Generated from the Markdown files in docs/ by <code>doc report</code>. Edit the files, not this page.</footer></main></body></html>")
    summary = {"project": project, "verified": verified, "live": len(live), "failed": len(failed),
               "unproven": len(unproven), "uncovered": len(uncovered) + len(bad_links), "proposed": len(proposed)}
    return "\n".join(out), summary

def cmd_report(args):
    """Write docs/report.html and open it."""
    page, sm = build_report(with_issues="--no-issues" not in args)
    path = p("docs", "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    print(c(f"{sm['project']} status", "1"))
    print(f"  requirements verified   {sm['verified']}/{sm['live']}")
    if sm["failed"]:
        warn(f"requirements failed     {sm['failed']}")
    print(f"  not yet tested          {sm['unproven']}")
    print(f"  uncovered failure modes {sm['uncovered']}")
    print(f"  decisions proposed      {sm['proposed']}")
    ok(f"Written: {rel(path)}")
    if "--no-open" not in args:
        opener = "open" if sys.platform == "darwin" else "xdg-open" if shutil.which("xdg-open") else None
        if opener:
            subprocess.run([opener, path], capture_output=True)

# ----------------------------------------------------------------- init

def cmd_init(args):
    """Copy the templates and this script into a project."""
    kit = os.path.dirname(os.path.abspath(__file__))
    template = os.path.join(kit, "template")
    if not os.path.isdir(template):
        sys.exit("init must be run from the doc-kit folder (template/ not found next to doc.py).")
    target = os.path.abspath(os.path.expanduser(args[0] if args else "."))
    if not os.path.isdir(target):
        sys.exit(f"Folder not found: {target}")
    default_name = os.path.basename(target.rstrip(os.sep))
    name = input(f"Project name [{default_name}]: ").strip() or default_name

    created, skipped = [], []
    for base, _, files in os.walk(template):
        for f in files:
            src = os.path.join(base, f)
            relpath = os.path.relpath(src, template)
            # template/github/ is stored without the dot; it becomes .github/
            if relpath.split(os.sep)[0] == "github":
                relpath = "." + relpath
            dst = os.path.join(target, relpath)
            if os.path.exists(dst):
                skipped.append(relpath)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(text.replace("{{PROJECT}}", name))
            created.append(relpath)

    tool = os.path.join(target, "tools", "doc.py")
    existed = os.path.exists(tool)
    os.makedirs(os.path.dirname(tool), exist_ok=True)
    shutil.copy2(os.path.abspath(__file__), tool)
    os.chmod(tool, 0o755)
    created.append("tools/doc.py (updated to " + __version__ + ")" if existed else "tools/doc.py")

    ok(f"\nSet up documentation for {name} in {target}")
    for f in sorted(created):
        print(f"  + {f}")
    for f in sorted(skipped):
        info(f"  = {f} (already exists, left unchanged)")
    print(c("\nNext steps:", "1"))
    print("  1. Edit the subsystem table in docs/README.md and the subsystem list")
    print("     in .github/ISSUE_TEMPLATE/*.yml to match your project.")
    print("  2. Add this shortcut line to ~/.zshrc or ~/.bashrc (once per computer):")
    print("""       alias doc='python3 "$(git rev-parse --show-toplevel)/tools/doc.py"'""")
    print("  3. Inside the project:  doc install-hook")
    print("  4. Optional, for doc idea / doc bug:  brew install gh && gh auth login")
    print("  5. Type  doc  and pick what just happened.")


def main():
    global ROOT
    args = sys.argv[1:]
    if args and args[0] == "init":
        try:
            return cmd_init(args[1:])
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(1)
    if args and args[0] in ("--version", "version"):
        return print(f"doc.py {__version__}")
    ROOT = find_root()
    try:
        if not args:
            run_with_back(cmd_menu)
        elif args[0] in ("-h", "--help", "help"):
            print(__doc__)
        elif args[0] == "test":
            run_with_back(lambda: cmd_test(args[1] if len(args) > 1 else None))
        elif args[0] == "update":
            run_with_back(lambda: cmd_update(args[1] if len(args) > 1 else None))
        elif args[0] == "hook":
            cmd_hook()
        elif args[0] == "report":
            cmd_report(args[1:])
        elif args[0] == "tidy":
            path = p("docs", "requirements.md")
            write(path, regroup_requirements(read(path)))
        elif args[0] == "install-hook":
            cmd_install_hook()
        elif args[0] in COMMANDS:
            run_with_back(COMMANDS[args[0]])
        else:
            sys.exit(f"Unknown command '{args[0]}'. Try: python3 tools/doc.py help")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing written.")
        sys.exit(1)


if __name__ == "__main__":
    main()
