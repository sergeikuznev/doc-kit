# Using the terminal

Everything the [page](PAGE.md) writes, the terminal writes too, through the
same code, so the files come out identical either way. Use the terminal when
you are already in a shell, on a machine without `doc serve`, offline, in a
script or CI, or for the records that have no form yet: procedures, checklist
lines and the devlog.

Concepts (what each record is for, good versus weak examples) are in the
[handbook](HANDBOOK.md).

**Contents**

1. [Setup](#1-setup)
2. [How answering works](#2-how-answering-works)
3. [Commands](#3-commands)
4. [Each command](#4-each-command)
5. [The system model from the terminal](#5-the-system-model-from-the-terminal)
6. [Hooks](#6-hooks)
7. [Workflows](#7-workflows)
8. [Scripts and CI](#8-scripts-and-ci)
9. [Updating doc-kit in a project](#9-updating-doc-kit-in-a-project)

---

## 1. Setup

```bash
git clone https://github.com/sergeikuznev/doc-kit.git
python3 doc-kit/doc.py init /path/to/your/project
```

`init` copies the templates into `docs/` (it never overwrites an existing
file) and the tool into `tools/`. Then, once per computer, add the shortcut to
`~/.zshrc` or `~/.bashrc`:

```bash
alias doc='python3 "$(git rev-parse --show-toplevel)/tools/doc.py"'
```

`doc` then works from any folder inside the project. Inside the project, once
per clone:

```bash
doc install-hook
```

Optional, for `doc idea`, `doc bug` and issues on the page: install the
[GitHub CLI](https://cli.github.com) and run `gh auth login`.

---

## 2. How answering works

Run `doc` with no arguments and it asks what just happened:

```
$ doc
What just happened?
    idea       I got an idea
    bug        Something behaves wrong (bug)
    decision   I chose between options
  ❯ req        I committed to building something
    fault      I asked 'what if this breaks?'
    test       I tested a requirement
    ...

  ↑↓ move · Enter select · type to filter · < back · << jump

Subsystem   filter: com
  ❯ COMM  Communications
New requirement COMM-003
Requirement
  Form: "The <thing> shall <do what> <measurable limit>."
> The robot shall stop all motors within 1 s of losing the radio link.
...
Write this?
  ❯ Write it
    Change an answer
    Cancel, write nothing
Written: docs/requirements.md
```

- **Choices are menus:** ↑↓ to move, Enter to select, or start typing to filter
  (`nav` jumps to NAV). You only type free text.
- **A preview pane under every menu** shows the highlighted item in full: the
  whole requirement with its evidence, every column of a fault row.
- **`<`** goes back one question (inside a list, it removes the last line).
- **`<<`** lists all your answers so far; pick one to change it and the rest are kept.
- After `<` or `<<` your previous answer comes back **filled in**, so you fix a
  typo instead of retyping. Editing keys: ←→, Option+←→ (word), Home/End or
  Ctrl+A/Ctrl+E, Ctrl+U (clear line), Ctrl+W (delete word).
- **Lists** (context, steps, consequences): one item per line, an empty line ends the list.
- At the end you choose **Write it**, **Change an answer** or **Cancel**. Nothing is written before that.
- **Ctrl+C** cancels at any point.

When input is piped or on Windows, menus fall back to typing a number or a key.
`DOC_PLAIN=1` forces that mode.

---

## 3. Commands

| Command | Does | Writes to | On the page |
|---|---|---|---|
| `doc` | Menu: what just happened? | | + New |
| `doc idea` | GitHub issue from your answers | GitHub Issues | + New → Idea |
| `doc bug` | Bug report issue | GitHub Issues | + New → Bug |
| `doc decision` | Decision record, next number | `docs/decisions/NNN-title.md` | + New → Decision |
| `doc req` | Requirement, next ID in its subsystem | `docs/requirements.md` | + New → Requirement |
| `doc test [ID]` | Test result and evidence | `docs/requirements.md` | Record test |
| `doc fault` | Failure mode row (FM-001, ...) | `docs/fdir.md` | + New → Fault |
| `doc update [ID]` | Change a status, text or link; requirement changes are logged | the file that holds it | Edit, Mark deleted, Change status |
| `doc procedure` | Numbered procedure | `docs/procedures/<title>.md` | terminal only |
| `doc check` | Checklist line plus a dated reason | `docs/procedures/pre_power_checklist.md` | terminal only |
| `doc log` | This week's devlog entry (adds to it if it exists) | `docs/devlog.md` | terminal only |
| `doc model setup` | Point the model at each board's `.ioc` and the ROS2 folders | `docs/model/model.toml`, starter arch file | |
| `doc model` | Rebuild the facts, check the wiring, write the page | `docs/model/<name>_facts.sysml`, `docs/system.html` | |
| `doc serve` | The page, live, with forms | `http://127.0.0.1:8765` | |
| `doc report` | Printable status summary | `docs/report.html` | Overview |
| `doc tidy` | Regroup requirements by subsystem | `docs/requirements.md` | |
| `doc install-hook` | Install the git hooks (section 6) | `.git/hooks/` | |
| `doc --version`, `doc help` | | | |

---

## 4. Each command

### `doc idea`, `doc bug`

Asks for a title, what and why (idea) or what happened, what should have
happened and how to reproduce it (bug), the subsystem, and the priority or
firmware version. Creates the issue with the subsystem as a label, creating
missing labels on GitHub first. Refer to it as `#N` in decisions and commits;
`fixes #N` in a commit message closes it.

### `doc decision`

Title (state the decision itself), status, related issues and requirement IDs,
which older decision it replaces, context, the options you compared with pros
and cons, which you chose, the decision in one or two sentences, the deciding
factor, consequences. With a replaced decision, the old one is marked
*Superseded by NNN*.

### `doc req`

Subsystem (from the prefix table in `docs/README.md`), the requirement
sentence, rationale, how it will be verified, status. Warns if the sentence has
no *shall* or no number to measure, and lets you keep it anyway.

### `doc test [ID]`

Without an ID it lists requirements, untested first. Asks Passed or Failed,
what you measured, the evidence file (put it in `docs/media/` first so it shows
on the page), and the date. Appends one dated line to the evidence; earlier
lines are kept.

### `doc fault`

What fails, the effect, how it is detected, the immediate response, recovery,
severity (1 annoying to 4 hardware damage), and the requirement that covers it.
Warns if that requirement does not exist or is deleted.

### `doc update [ID]`

`doc update COMM-002` (requirement), `doc update FM-003` (fault),
`doc update 2` (decision), or `doc update` to pick. Requirements: status, text,
rationale or method; every change is added to the change log at the bottom of
`requirements.md`, and changing the text of a Verified requirement offers to
set it back to Approved for a retest. *Deleted* asks why and keeps the row.

### `doc procedure`

Title, what it applies to, rough time, tools and parts, steps in order,
warnings, a photo file name. One file per procedure.

### `doc check`

The check as something you can tick, why it was added (what broke or nearly
broke), and the section. Adds the line to the pre-power checklist and a dated
row to its history.

### `doc log`

Done this week, what broke or what you learned, next steps, media saved. If
this week's entry already exists, adds to it.

### `doc report`

Writes `docs/report.html`, a one-page printable status: requirement progress
per subsystem, everything that needs attention (failed or untested
requirements, faults with no requirement, decisions still proposed),
fault-to-requirement links, the latest devlog entry, recent requirement
changes, open issues. Options: `--no-open`, `--no-issues`.

---

## 5. The system model from the terminal

```bash
doc model setup     # once
doc model           # rebuild, check, write docs/system.html and open it
doc model --check   # check only; exit code 1 if the wiring is broken
doc model --no-open --no-issues
doc serve [--port 8765] [--interval 60] [--no-push]
```

`doc model setup` lists every `.ioc` in the repo and asks, for each board,
which file, a short name for it, and which subsystem it sits in, then which
folders to scan for ROS2 and micro-ROS code. It writes
`docs/model/model.toml` (which you can edit by hand) and a starter arch file.
A board always points at one exact `.ioc` file, so folder names do not matter.

`doc model` prints a summary and any problems:

```
Written: docs/model/CHIMERA_facts.sysml
Written: docs/system.html

1 model problem(s): the architecture no longer matches the facts
  ✕ docs/model/CHIMERA_arch.sysml:78: connect CTRL.mcu.nrf24_ce to COMM.radio.ce:
    chimera.CTRL.mcu has no port 'nrf24_ce' (it is not in the .ioc any more - pin renamed or removed?)

  6 subsystems, 12 parts, 24 connections, 3 ROS2 nodes, 8 gaps (listed in the page)
```

Writing the arch file is explained in the [handbook](HANDBOOK.md#15-the-system-model).

---

## 6. Hooks

`doc install-hook` installs two git hooks in this clone (hooks are not shared
through the repo, so each person runs it once):

- **pre-commit**: when `docs/model/model.toml` exists, regenerates the facts
  from the `.ioc`, ROS2 code and docs, adds the facts file to the commit, and
  stops the commit if the wiring no longer matches:
  ```
  Commit stopped. Fix the arch file, or commit anyway with: git commit --no-verify
  ```
- **post-commit**: after a commit whose message closes an issue (`fixes #12`),
  asks whether it created a decision, requirement, test result, procedure or
  fault row, and opens that command.

---

## 7. Workflows

The same workflows as in [the page guide](PAGE.md#9-workflows), in the shell.

### First setup

```bash
python3 path/to/doc-kit/doc.py init .
doc install-hook
doc model setup
$EDITOR docs/model/CHIMERA_arch.sysml     # modules and wiring
doc model                                 # until it reports no problems
```

### Record a test

```bash
cp ~/Desktop/stop_test.mp4 docs/media/2026-11-27_stop_test.mp4
doc test COMM-002      # Passed · "stopped after 0.4 s, 5 runs" · 2026-11-27_stop_test.mp4
git commit -am "test: COMM-002 verified"
```

### From an idea to a verified requirement

```bash
doc idea               # becomes issue #12
doc decision           # Related: #12
doc req                # COMM-003
doc fault              # covered by COMM-003
# build it
git commit -m "feat(comm): link-loss stop, fixes #12"   # the post-commit hook offers doc test
doc test COMM-003
```

### A test fails

```bash
doc test COMM-002      # Failed · what you saw
doc bug                # steps and the evidence file
doc check              # if something nearly broke
```

### A pin changed in CubeMX

```bash
git commit -am "cubemx: rename CE pin"    # stopped by the hook, with the arch file line
$EDITOR docs/model/CHIMERA_arch.sysml
git commit -am "cubemx: rename CE pin"
```

### Weekly review

```bash
doc report             # read Needs attention
doc log
```

---

## 8. Scripts and CI

- `DOC_PLAIN=1` turns menus into numbered prompts, so answers can be piped:
  ```bash
  printf 'COMM\nThe link shall recover within 2 s\nOperators need it back\nT\nDraft\ny\n' | DOC_PLAIN=1 doc req
  ```
- `doc model --check` exits 1 when the wiring is broken. In GitHub Actions:
  ```yaml
  - uses: actions/setup-python@v5
    with: { python-version: "3.12" }
  - run: python3 tools/doc.py model --check
  ```
- `doc report --no-open --no-issues` and `doc model --no-open --no-issues` build the pages without a browser or GitHub.

---

## 9. Updating doc-kit in a project

```bash
cd path/to/doc-kit && git pull
python3 doc.py init path/to/your/project
cd path/to/your/project && doc install-hook
```

`init` replaces everything in `tools/` and leaves your docs untouched. Run
`doc install-hook` again when a new version adds hooks.
