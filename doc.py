#!/usr/bin/env python3
"""
doc.py - doc-kit: engineering records and a live system model for hardware projects.
https://github.com/sergeikuznev/doc-kit

The page (doc serve) is where you work: requirements, tests, faults, decisions,
procedures, issues, subsystems, boards, parts and wiring all have forms there.
These commands set a project up and run the checks:

    python3 doc.py init /path/to/project    install doc-kit into a project (run from the doc-kit folder)
    doc install-hook                         commit check + reminder hook for this clone
    doc serve [--port 8765] [--no-push]      the page: opens http://127.0.0.1:8765 in your browser
    doc model [--check] [--no-open]          rebuild the facts, check the architecture, write docs/system.html
    doc report [--no-open]                   static status page docs/report.html

(doc = python3 tools/doc-kit/doc.py; see tools/doc-kit/guides/TERMINAL.md)
"""

__version__ = "0.5.0"

import datetime
import html
import os
import re
import shutil
import subprocess
import sys

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


# ----------------------------------------------------------------- record operations
# Pure functions: answers in, file changes out. The terminal commands and the
# web server (doc serve) both call these, so both write identical files.

class OpError(Exception):
    pass

def req_text_problems(text):
    probs = []
    if "shall" not in text.lower():
        probs.append('no "shall"')
    if not re.search(r"\d", text):
        probs.append("no number to measure")
    return probs

def op_decision(title, status, related, supersedes, context, options, decision_text, factor, consequences):
    """options: list of (name, pros, cons). Returns (writes, text, notes)."""
    folder = p("docs", "decisions")
    existing = [f for f in os.listdir(folder)] if os.path.isdir(folder) else []
    nums = [int(f[:3]) for f in existing if re.match(r"\d{3}-", f)]
    num = max([n for n in nums if n > 0], default=0) + 1
    if not title.strip() or not decision_text.strip() or not factor.strip():
        raise OpError("title, decision and deciding factor are required")
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
    writes = [(p("docs", "decisions", f"{num:03d}-{slugify(title)}.md"), text)]
    notes = []
    if supersedes:
        old = [f for f in existing if f.startswith(f"{int(supersedes):03d}-")]
        if old:
            op_ = p("docs", "decisions", old[0])
            writes.append((op_, re.sub(r"(\*\*Status:\*\*)\s*[^\n]*", rf"\1 Superseded by {num:03d}", read(op_), count=1)))
        else:
            notes.append(f"Decision {int(supersedes):03d} not found; mark it superseded by hand.")
    return writes, text, notes

def op_requirement(prefix, shall, rationale, method, status):
    if prefix not in [r[0] for r in subsystem_rows()]:
        raise OpError(f"{prefix} is not a subsystem. Add it on the page under Setup first.")
    path = p("docs", "requirements.md")
    rid = next_id(table_rows(path, REQ_HEADER), prefix)
    cells = [rid, cell(shall), cell(rationale), method, status, ""]
    return [(path, insert_requirement(load_requirements(path), prefix, cells))], join_row(cells), rid

def _req_row(rid):
    rows = table_rows(p("docs", "requirements.md"), REQ_HEADER)
    match = [r for r in rows if r[0] == rid.upper()]
    if not match:
        raise OpError(f"{rid} not found in requirements.md")
    return match[0] + [""] * (6 - len(match[0]))

def op_test(rid, result, measured, evidence, date):
    path = p("docs", "requirements.md")
    row = _req_row(rid)
    entry = f"{date}: {measured}" + (f". {evidence}" if evidence else "")
    row[4] = result
    row[5] = cell(entry) if not row[5] else row[5] + "<br>" + cell(entry)
    lines = load_requirements(path).splitlines()
    _replace_row(lines, REQ_HEADER, row[0], row)
    return [(path, "\n".join(lines) + "\n")], join_row(row)

def req_link_problem(rid):
    status = {r[0]: (r[4] if len(r) > 4 else "") for r in table_rows(p("docs", "requirements.md"), REQ_HEADER)}
    rid = rid.upper()
    if rid not in status:
        return f"{rid} is not in requirements.md yet. Add the requirement first."
    if status[rid] == "Deleted":
        return f"{rid} is marked Deleted. Link a requirement that is still active."
    return None

def op_fault(failure, effect, detection, response, recovery, sev, req):
    path = p("docs", "fdir.md")
    fid = next_id(table_rows(path, FDIR_HEADER), "FM")
    cells = [fid] + [cell(x) for x in (failure, effect, detection, response, recovery)] + [sev, req.upper()]
    base = read(path) if os.path.exists(path) else "# Fault table (FDIR / FMEA)\n"
    return [(path, insert_row(base, FDIR_HEADER, cells))], join_row(cells), fid

def op_update_requirement(rid, new, change):
    """new: the full row (6 cells). change: the change-log text."""
    path = p("docs", "requirements.md")
    lines = load_requirements(path).splitlines()
    _replace_row(lines, REQ_HEADER, rid, new)
    text = "\n".join(lines) + "\n"
    if not any(l.strip() == "## Change log" for l in lines):
        text = text.rstrip() + "\n\n## Change log\n\n" + CHANGE_HEADER + "\n|---|---|---|\n"
    text = insert_row(text, CHANGE_HEADER, [today(), rid, cell(change)])
    return [(path, text)]

def _fault_row(fid):
    rows = table_rows(p("docs", "fdir.md"), FDIR_HEADER)
    match = [r for r in rows if r[0] == fid.upper()]
    if not match:
        raise OpError(f"{fid} not found in fdir.md")
    return match[0] + [""] * (8 - len(match[0]))

def op_update_fault(fid, new):
    path = p("docs", "fdir.md")
    lines = read(path).splitlines()
    _replace_row(lines, FDIR_HEADER, fid, new)
    return [(path, "\n".join(lines) + "\n")]

def op_update_decision(num, field, value):
    match = [d for d in _decisions() if d[0] == str(num).zfill(3)]
    if not match:
        raise OpError(f"No decision {num}")
    path = p("docs", "decisions", match[0][1])
    text = read(path)
    if field == "status":
        text = re.sub(r"(\*\*Status:\*\*)[^\n]*", lambda m: f"{m.group(1)} {value}", text, count=1)
    elif re.search(r"\*\*Related:\*\*", text):
        text = re.sub(r"(\*\*Related:\*\*)[^\n]*", lambda m: f"{m.group(1)} {value}", text, count=1)
    else:
        text = re.sub(r"(- \*\*Status:\*\*[^\n]*\n)", lambda m: m.group(1) + f"- **Related:** {value}\n", text, count=1)
    return [(path, text)]

def issue_body(kind, f):
    if kind == "idea":
        body = "\n".join([section("What", f["what"]), section("Why", f["why"]), section("Subsystem", [f["sub"]]),
                          section("Priority", [f["prio"]]), section("Open questions", [f"- {q}" for q in f.get("questions", [])])])
        return body, ["idea", f["sub"], f["prio"]]
    body = "\n".join([section("What happened", f["happened"]), section("What should have happened", f["expected"]),
                      section("Steps to reproduce", [f"{i}. {s}" for i, s in enumerate(f.get("steps", []), 1)]),
                      section("Subsystem", [f["sub"]]), section("Firmware version / commit", [f["firmware"]] if f.get("firmware") else []),
                      section("Logs, photos, videos", [f"- {e}" for e in f.get("evidence", [])])])
    return body, ["bug", f["sub"]]

def gh_create_issue(title, body, labels):
    """Returns (number, url). Raises OpError when GitHub refuses."""
    ensure_labels(labels)
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels:
        cmd += ["--label", label]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise OpError("GitHub refused the issue: " + r.stderr.strip())
    url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    return url.rstrip("/").rsplit("/", 1)[-1], url

def apply_writes(writes):
    for path, text in writes:
        write(path, text)

# ----------------------------------------------------------------- requirement

def subsystem_rows(include_deleted=False):
    """[(prefix, name, box, deleted)] from docs/model/model.toml (Setup on the page).
    Repos set up before 0.3 fall back to the table in docs/README.md. No defaults."""
    try:
        import tomllib
        with open(p("docs", "model", "model.toml"), "rb") as f:
            cfg = tomllib.load(f)
    except (OSError, ImportError, ValueError):
        cfg = {}
    rows = [(s["prefix"], s.get("name", s["prefix"]), s.get("box", True), bool(s.get("deleted")))
            for s in cfg.get("subsystem", []) if s.get("prefix")]
    if not rows:
        rows = [(r[0], r[1], True, False) for r in table_rows(p("docs", "README.md"), "| Prefix | Subsystem |")
                if len(r) >= 2 and re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", r[0])]
    return [r for r in rows if include_deleted or not r[3]]

def req_prefixes():
    """(prefix, name) of every subsystem, in Setup order; deleted ones keep their place
    so old requirement sections stay where they were."""
    return [(r[0], r[1]) for r in subsystem_rows(include_deleted=True)]

REQ_SEP = "|---|---|---|---|---|---|"

def _section_prefix(line):
    m = re.match(r"##\s+([A-Z][A-Z0-9]{1,5})\b", line)
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

# ----------------------------------------------------------------- update

CHANGE_HEADER = "| Date | ID | Change |"
DEC_STATUSES = [("Proposed", "Proposed"), ("Accepted", "Accepted"),
                ("Rejected", "Rejected"), ("Superseded", "Superseded by a newer decision")]
REQ_STATUSES = [("Draft", "Draft"), ("Approved", "Approved"), ("Verified", "Verified"),
                ("Failed", "Failed"), ("Deleted", "Deleted (dropped; the ID is never reused)")]

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


# ----------------------------------------------------------------- procedures, checklist, devlog

def op_procedure(title, applies, duration, needs, steps, warnings, photo):
    if not title.strip() or not steps:
        raise OpError("a title and at least one step are required")
    path = p("docs", "procedures", slugify(title).replace("-", "_") + ".md")
    if os.path.exists(path):
        raise OpError(f"{rel(path)} already exists. Edit that file instead.")
    out = [f"# Procedure: {title}", ""]
    if applies:
        out.append(f"- **Applies to:** {applies}")
    if duration:
        out.append(f"- **Time:** {duration}")
    out.append(f"- **Last updated:** {today()}")
    if needs:
        out += ["", "## You need"] + [f"- {x}" for x in needs]
    out += ["", "## Steps"] + [f"{i}. {s_}" for i, s_ in enumerate(steps, 1)]
    for w in warnings:
        out += ["", f"> **Warning:** {w}"]
    if photo:
        out += ["", "## Photos", f"`media/{photo}`"]
    text = "\n".join(out) + "\n"
    return [(path, text)], text

def checklist_sections():
    path = p("docs", "procedures", "pre_power_checklist.md")
    if not os.path.exists(path):
        return []
    return [l[3:].strip() for l in read(path).splitlines() if l.startswith("## ") and l[3:].strip() != "History"]

def op_check(item, why, section):
    if not item.strip() or not why.strip() or not section.strip():
        raise OpError("the check, the reason and the section are required")
    path = p("docs", "procedures", "pre_power_checklist.md")
    text = read(path) if os.path.exists(path) else "# Pre-power checklist\n\n## Checks\n\n## History\n| Date | Line added | Why |\n|---|---|---|\n"
    lines = text.splitlines()
    heads = [i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip() == section]
    if not heads:
        h = next((i for i, l in enumerate(lines) if l.strip() == "## History"), len(lines))
        lines[h:h] = [f"## {section}", f"- [ ] {item}", ""]
    else:
        i = heads[0] + 1
        last = i
        while i < len(lines) and not lines[i].startswith("## "):
            if lines[i].startswith("- ["):
                last = i
            i += 1
        lines.insert(last + 1 if last > heads[0] else heads[0] + 1, f"- [ ] {item}")
    if not any(l.strip() == "## History" for l in lines):
        lines += ["", "## History"]
    new = insert_row("\n".join(lines), HIST_HEADER, [today(), cell(item), cell(why)])
    return [(path, new)], f"## {section}\n- [ ] {item}\n\nHistory: {today()} | {item} | {why}"

LOG_SECTIONS = [("**Done**", "done"), ("**Broke / learned**", "broke"), ("**Next**", "next"), ("**Media**", "media")]

def op_log(answers):
    """answers: {"done": [...], "broke": [...], "next": [...], "media": [...]}. Adds to this week's entry."""
    if not answers.get("done"):
        raise OpError("'Done this week' needs at least one line")
    path = p("docs", "devlog.md")
    d = datetime.date.today()
    heading = f"## Week of {(d - datetime.timedelta(days=d.weekday())).isoformat()}"
    text = read(path) if os.path.exists(path) else "# Devlog\n\nNewest entry at the top.\n\n---\n"
    lines = text.splitlines()
    if heading in lines:
        start = lines.index(heading) + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ") or lines[i].strip() == "---"), len(lines))
        block = lines[start:end]
        for label, key in LOG_SECTIONS:
            items = [f"- {x}" for x in answers.get(key, [])]
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
        preview = f"(added to {heading[3:]})\n" + "\n".join(
            f"{l}\n" + "\n".join(f"- {x}" for x in answers.get(k, [])) for l, k in LOG_SECTIONS if answers.get(k))
    else:
        entry = [heading, ""]
        for label, key in LOG_SECTIONS:
            if answers.get(key):
                entry += [label] + [f"- {x}" for x in answers[key]] + [""]
        entry.append("---")
        sep = next((i for i, l in enumerate(lines) if l.strip() == "---"), None)
        at = sep + 1 if sep is not None else len(lines)
        lines[at:at] = [""] + entry
        preview = "\n".join(entry)
    return [(path, "\n".join(lines).rstrip() + "\n")], preview


# ----------------------------------------------------------------- GitHub issues

def subsystems():
    """Issue labels: the subsystem prefixes in lowercase (Setup writes the same list
    into .github/ISSUE_TEMPLATE/*.yml). Older repos: the list in idea.yml."""
    rows = subsystem_rows()
    if rows:
        return [r[0].lower() for r in rows]
    path = p(".github", "ISSUE_TEMPLATE", "idea.yml")
    if os.path.exists(path):
        m = re.search(r"id:\s*subsystem.*?options:\s*\[([^\]]*)\]", read(path), re.S)
        if m:
            return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    return []

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

def cmd_hook():
    """Called by the git post-commit hook: a reminder, never a question."""
    try:
        msg = subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=ROOT, capture_output=True, text=True).stdout
    except OSError:
        return
    issues = re.findall(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", msg, re.I)
    if issues:
        print(c(f"This commit closes #{', #'.join(issues)}. If it settled a choice, proved a requirement or "
                f"changed a procedure, record it on the page (+ New).", "36"))

HOOK = """#!/bin/sh
# Installed by doc-kit: after a commit that closes an issue, print a reminder
# to record the decision / test / procedure on the page.
python3 "$(git rev-parse --show-toplevel)/tools/doc-kit/doc.py" hook || true
"""

PRE_HOOK = """#!/bin/sh
# Installed by doc-kit: regenerate the model facts (.ioc, ROS2 code, docs)
# and stop the commit if the architecture no longer matches them.
ROOT="$(git rev-parse --show-toplevel)"
[ -f "$ROOT/docs/model/model.toml" ] || exit 0
python3 "$ROOT/tools/doc-kit/doc.py" model --hook
"""


def cmd_install_hook():
    gitdir = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if not gitdir:
        sys.exit("Not a git repository.")
    hook = os.path.join(ROOT, gitdir, "hooks", "post-commit")
    if os.path.exists(hook) and "tools/doc" not in read(hook) and "doc-kit" not in read(hook):
        sys.exit(f"{hook} already exists and was not made by doc.py. Merge it by hand.")
    os.makedirs(os.path.dirname(hook), exist_ok=True)
    with open(hook, "w") as f:
        f.write(HOOK)
    os.chmod(hook, 0o755)
    ok("Installed post-commit hook: after a commit with 'fixes #N' it reminds you to record what came out of it.")
    pre = os.path.join(ROOT, gitdir, "hooks", "pre-commit")
    if os.path.exists(pre) and "tools/doc" not in read(pre) and "doc-kit" not in read(pre):
        warn(f"{pre} already exists and was not made by doc.py; the model check was not installed.")
    else:
        with open(pre, "w") as f:
            f.write(PRE_HOOK)
        os.chmod(pre, 0o755)
        ok("Installed pre-commit hook. When docs/model/model.toml exists, each commit rebuilds the facts and checks the architecture.")



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
      + (f" · last commit {html.escape(commit)}" if commit else "")
      + (" · <a href='system.html'>system map</a>" if os.path.exists(p("docs", "system.html")) else "") + " · by doc-kit</div>")

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
        w("<div class='empty'>No requirements yet. Add one on the page: + New › Requirement.</div>")
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
        w("<div class='empty'>No failure modes yet. Add one on the page: + New › Fault.</div>")
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
        w("<div class='empty'>No entries yet. Add one on the page: + New › Devlog.</div>")
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

    w("<footer>Generated from the Markdown files in docs/ by <code>doc report</code>. Change them on the page (doc serve), not here.</footer></main></body></html>")
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


# ----------------------------------------------------------------- system model

def _docmodel():
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(here, "docmodel.py")):
        sys.exit("doc model needs docmodel.py next to doc.py. Re-run: python3 <doc-kit>/doc.py init <project>")
    sys.path.insert(0, here)
    import docmodel
    return docmodel

def _open(path):
    opener = "open" if sys.platform == "darwin" else "xdg-open" if shutil.which("xdg-open") else None
    if opener:
        subprocess.run([opener, path], capture_output=True)

def cmd_model(args):
    """Rebuild the facts from the .ioc files, ROS2 code and docs; check the architecture; write docs/system.html."""
    dm = _docmodel()
    if args and args[0] == "setup":
        sys.exit("doc model setup is gone: add boards, subsystems and ROS2 folders on the page (doc serve > Setup).")
    hook = "--hook" in args
    try:
        m = dm.build(ROOT)
    except dm.ModelError as e:
        if hook and "model.toml" in str(e):
            return
        print(c(f"doc model: {e}", "1;31"))
        sys.exit(1)
    facts = p("docs", "model", f"{m['name']}_facts.sysml")
    text = dm.facts_sysml(m)
    if not os.path.exists(facts) or read(facts) != text:
        write(facts, text)
        if hook:
            subprocess.run(["git", "add", facts], cwd=ROOT)
    if not hook and "--check" not in args:
        dm.collect_extras(ROOT, m, with_issues="--no-issues" not in args)
        if m["issue_error"] not in (None, "skipped"):
            info(f"  issues not included: {m['issue_error']}")
        page = p("docs", "system.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(dm.page(m))
        ok(f"Written: {rel(page)}")
    if m["problems"]:
        print(c(f"\n{len(m['problems'])} model problem(s): the architecture no longer matches the facts", "1;31"))
        for x in m["problems"]:
            print(c(f"  ✕ {x}", "31"))
    for x in m["notes"]:
        info(f"  note: {x}")
    if not hook:
        print(f"\n  {len(m['subsystems'])} subsystems, {sum(1 for x in m['parts'].values() if x['depth'] >= 2)} parts, "
              f"{sum(1 for x in m['connections'] if x['ok'])} connections, {len(m['nodes'])} ROS2 nodes, "
              f"{len(m['gaps'])} gaps (listed in the page)")
    if m["problems"]:
        if hook:
            print(c("\nCommit stopped. Fix the wiring on the page (doc serve > Edit), or commit anyway with: git commit --no-verify", "1"))
        sys.exit(1)
    if not hook and "--check" not in args and "--no-open" not in args:
        _open(p("docs", "system.html"))

def cmd_serve(args):
    """Serve the system map with forms on this machine (share it with: tailscale serve --bg PORT)."""
    _docmodel()
    import docserve
    docserve.doc = sys.modules[__name__]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8765
    interval = int(args[args.index("--interval") + 1]) if "--interval" in args else 60
    docserve.serve(ROOT, port=port, push="--no-push" not in args, interval=interval, open_browser="--no-open" not in args)


# ----------------------------------------------------------------- init

PROJECT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

def cmd_init(args):
    """Copy the templates and doc-kit's tools into a project. Asks only for the project name."""
    kit = os.path.dirname(os.path.abspath(__file__))
    template = os.path.join(kit, "template")
    if not os.path.isdir(template):
        sys.exit("init must be run from the doc-kit folder (template/ not found next to doc.py).")
    rest = [a for a in args if not a.startswith("--")]
    target = os.path.abspath(os.path.expanduser(rest[0] if rest else "."))
    if not os.path.isdir(target):
        sys.exit(f"Folder not found: {target}")
    cfg = os.path.join(target, "docs", "model", "model.toml")
    name = None
    if os.path.exists(cfg):  # re-running init only updates the tools
        m = re.search(r'^name\s*=\s*"([^"]+)"', open(cfg, encoding="utf-8").read(), re.M)
        name = m.group(1) if m else None
    if "--name" in args:
        name = args[args.index("--name") + 1]
    while not name or not PROJECT_NAME.match(name):
        if name:
            warn("Use letters, digits and _ only, starting with a letter (it becomes part of file names).")
        name = input("Project name (used in file names, e.g. ROVER_1): ").strip()

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
    _drop_old_defaults(target)
    if not os.path.exists(cfg):
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write("# doc-kit model settings. Edited from the page (Setup). Hand edits are fine,\n"
                     "# but the page rewrites this file in this layout.\n\n"
                     f'[project]\nname = "{name}"\n\n[ros]\npaths = []\n')
        created.append("docs/model/model.toml")

    home = os.path.join(target, "tools", "doc-kit")  # everything doc-kit installs lives in this one folder
    tool = os.path.join(home, "doc.py")
    existed = os.path.exists(tool) or os.path.exists(os.path.join(target, "tools", "doc.py"))
    os.makedirs(home, exist_ok=True)
    shutil.copy2(os.path.abspath(__file__), tool)
    os.chmod(tool, 0o755)
    created.append("tools/doc-kit/doc.py (updated to " + __version__ + ")" if existed else "tools/doc-kit/doc.py")
    for extra in ("docmodel.py", "docmodel_page.html", "docserve.py", "docedit.py", os.path.join("vendor", "elk.bundled.js"),
                  os.path.join("vendor", "LICENSE-elkjs.md"), "README.md", os.path.join("docs", "PAGE.md"),
                  os.path.join("docs", "TERMINAL.md"), os.path.join("docs", "HANDBOOK.md")):
        src = os.path.join(kit, extra)
        if os.path.exists(src):
            dst = os.path.join(home, "guides", os.path.basename(extra)) if extra.endswith(".md") and "LICENSE" not in extra \
                else os.path.join(home, extra)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    created.append("tools/doc-kit/ (docmodel.py, docserve.py, docedit.py, docmodel_page.html, vendor/, guides/)")
    gi = os.path.join(home, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as fh:
            fh.write("__pycache__/\n")
    moved = _move_old_layout(target)
    if moved:
        created.append(f"moved out of tools/: {', '.join(moved)}")

    ok(f"\nSet up documentation for {name} in {target}")
    for f in sorted(created):
        print(f"  + {f}")
    for f in sorted(skipped):
        info(f"  = {f} (already exists, left unchanged)")
    print(c("\nNext steps:", "1"))
    print("  1. Once per computer, add the shortcut to ~/.zshrc or ~/.bashrc:")
    print("""       alias doc='python3 "$(git rev-parse --show-toplevel)/tools/doc-kit/doc.py"'""")
    print("     (an older alias pointing at tools/doc.py must be changed to tools/doc-kit/doc.py)")
    print("  2. Commit what init created, then inside the project:  doc install-hook")
    print("  3. doc serve    and open http://127.0.0.1:8765")
    print("  4. On the page, open Setup: add your subsystems, boards (.ioc files) and ROS2 code folders.")
    print("     Then build the wiring in the System views with Edit.")
    print("  Optional: brew install gh && gh auth login   (issues on the page, idea and bug forms)")


OLD_TABLE = """| Prefix | Subsystem |
|---|---|
| SYS | Whole system |
| COMM | Communications |
| PWR | Power |
| MOT | Motors and actuators |
| SENS | Sensors and perception |
| SW | Software |
| MECH | Mechanical |
| FDIR | Fault detection, isolation and recovery |"""
OLD_OPTIONS = "options: [comms, power, motors, sensors, software, mech, fdir, other]"

def _drop_old_defaults(target):
    """Projects set up with doc-kit 0.2 got a default subsystem list. If it was never
    edited, clear it, so Setup on the page starts empty (no defaults)."""
    readme = os.path.join(target, "docs", "README.md")
    if os.path.exists(readme) and OLD_TABLE in read(readme):
        write(readme, read(readme).replace(OLD_TABLE, "<!-- doc-kit:subsystems (edit on the page: Setup) -->\n| Prefix | Subsystem |\n|---|---|\n<!-- /doc-kit:subsystems -->"))
    for f in ("idea.yml", "bug.yml"):
        path = os.path.join(target, ".github", "ISSUE_TEMPLATE", f)
        if os.path.exists(path) and OLD_OPTIONS in read(path):
            write(path, read(path).replace(OLD_OPTIONS, "options: [general]   # written from the page (Setup): your subsystem prefixes in lowercase"))


OLD_FILES = ["doc.py", "docmodel.py", "docserve.py", "docedit.py", "docmodel_page.html",
             os.path.join("vendor", "elk.bundled.js"), os.path.join("vendor", "LICENSE-elkjs.md")]

def _move_old_layout(target):
    """doc-kit up to 0.4 put its files straight into tools/. Remove those copies (they are now in
    tools/doc-kit/), and point hooks and the Pages workflow at the new place."""
    tools, gone = os.path.join(target, "tools"), []
    old_doc = os.path.join(tools, "doc.py")
    if os.path.exists(old_doc) and "doc-kit" in read(old_doc):
        for f in OLD_FILES:
            pth = os.path.join(tools, f)
            if os.path.exists(pth):
                os.remove(pth)
                gone.append(f.replace(os.sep, "/"))
        for d in ("guides", "vendor", "__pycache__"):
            pth = os.path.join(tools, d)
            if d == "guides" and os.path.isdir(pth):
                shutil.rmtree(pth)
                gone.append("guides/")
            elif os.path.isdir(pth) and (d == "__pycache__" or not os.listdir(pth)):
                shutil.rmtree(pth)
        gi = os.path.join(tools, ".gitignore")
        if os.path.exists(gi) and read(gi).strip() == "__pycache__/":
            os.remove(gi)
    hooks = os.path.join(target, ".git", "hooks")
    for f in ("pre-commit", "post-commit"):
        pth = os.path.join(hooks, f)
        if os.path.exists(pth) and "tools/doc.py" in read(pth):
            text = read(pth).replace("tools/doc.py", "tools/doc-kit/doc.py")
            with open(pth, "w") as fh:
                fh.write(text)
    wf = os.path.join(target, ".github", "workflows", "doc-kit-pages.yml")
    if os.path.exists(wf) and "tools/doc.py" in read(wf):
        text = read(wf).replace("tools/doc.py", "tools/doc-kit/doc.py")
        with open(wf, "w") as fh:
            fh.write(text)
    return gone

MOVED = {"req", "test", "fault", "decision", "procedure", "check", "log", "idea", "bug", "update", "tidy"}

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
    if not args or args[0] in ("-h", "--help", "help"):
        return print(__doc__)
    ROOT = find_root()
    cmd = args[0]
    try:
        if cmd == "hook":
            cmd_hook()
        elif cmd == "report":
            cmd_report(args[1:])
        elif cmd == "model":
            cmd_model(args[1:])
        elif cmd == "serve":
            cmd_serve(args[1:])
        elif cmd == "install-hook":
            cmd_install_hook()
        elif cmd in MOVED:
            sys.exit(f"'doc {cmd}' is now a form on the page: run  doc serve  and use + New (or the buttons on each record).")
        else:
            sys.exit(f"Unknown command '{cmd}'. Try: doc help")
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        sys.exit(1)


if __name__ == "__main__":
    main()
