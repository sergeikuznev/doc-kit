# Using the terminal

doc-kit is used on the page ([PAGE.md](PAGE.md)). The terminal is only for
what the page cannot do for itself: installing doc-kit into a project, the git
hooks of your clone, starting the server, and checks in scripts and CI.

| Command | What it does |
|---|---|
| `python3 doc.py init <project>` | install or update doc-kit in a project (run from the doc-kit folder) |
| `doc install-hook` | install the commit check and the reminder hook in this clone |
| `doc serve` | start the page |
| `doc model` | rebuild the facts, check the wiring, write `docs/system.html` |
| `doc report` | write the static status page `docs/report.html` |
| `doc help`, `doc version` | |

**Contents**

1. [Installing doc-kit in a project](#1-installing-doc-kit-in-a-project)
2. [The shortcut](#2-the-shortcut)
3. [Hooks](#3-hooks)
4. [The server](#4-the-server)
5. [Checks without the page](#5-checks-without-the-page)
6. [Scripts and CI](#6-scripts-and-ci)
7. [Updating doc-kit in a project](#7-updating-doc-kit-in-a-project)
8. [What moved to the page](#8-what-moved-to-the-page)

---

## 1. Installing doc-kit in a project

```bash
git clone https://github.com/sergeikuznev/doc-kit.git
python3 doc-kit/doc.py init /path/to/your/project
```

It asks one thing: the **project name**, used in file names
(`docs/model/<name>_arch.sysml`), so letters, digits and `_` only. Pass
`--name ROVER_1` to skip the question. Everything else (subsystems, boards,
ROS2 folders) is added on the page under **Setup**: `init` fills in no defaults.

It creates, and never overwrites:

```
docs/README.md                how the docs work; its subsystem table is written by Setup
docs/requirements.md, fdir.md, devlog.md
docs/decisions/, procedures/, icd/, media/
docs/model/model.toml         project name; Setup adds subsystems, boards, ROS2 folders
.github/ISSUE_TEMPLATE/       Idea and Bug forms; Setup writes their subsystem list
tools/doc-kit/                doc.py, docmodel.py, docserve.py, docedit.py, the page, vendor/elkjs, guides/
```

Commit what it created.

---

## 2. The shortcut

Add once per computer, to `~/.zshrc` or `~/.bashrc`:

```bash
alias doc='python3 "$(git rev-parse --show-toplevel)/tools/doc-kit/doc.py"'
```

`doc` then works from any folder inside any project that has doc-kit.

---

## 3. Hooks

`doc install-hook` installs two git hooks in this clone. Hooks are not shared
through the repo, so each person who commits runs it once.

- **pre-commit**: regenerates `<name>_facts.sysml` from the `.ioc` files, the
  ROS2 code and the records, adds it to the commit, and stops the commit when
  the wiring no longer matches the facts:
  ```
  ✕ docs/model/ROVER_arch.sysml:102: connect CTRL.mcu.nrf24_ce to COMM.radio.ce:
    rover.CTRL.mcu has no port 'nrf24_ce' (it is not in the .ioc any more - pin renamed or removed?)

  Commit stopped. Fix the wiring on the page (doc serve > Edit), or commit anyway with: git commit --no-verify
  ```
- **post-commit**: after a commit whose message closes an issue (`fixes #12`),
  prints a reminder to record what came out of it (a decision, a test result, a procedure) on the page.

Commits made by the page skip the check, so a half-finished wiring change
is never blocked; problems show on the page instead.

---

## 4. The server

```bash
doc serve [--port 8765] [--interval 60] [--no-push] [--no-open]
```

- Serves the page at `http://127.0.0.1:8765` (this computer only) and opens it in your browser; `--no-open` skips that.
  Share it with your own devices with `tailscale serve --bg 8765`.
- Every `--interval` seconds: `git pull --ff-only`, and a rebuild when any input
  changed (the `.ioc` files, the ROS2 folders, `docs/`). GitHub issues refresh every 5 minutes.
- Each form writes files, commits them with a `doc: …` message and pushes
  (`--no-push`: commit only).
- It refuses to write a file that has uncommitted changes in this clone.
- Ctrl+C stops it. It runs only while that terminal is open and the computer is awake.

Details and the long-term setup on a lab PC: [PAGE.md](PAGE.md#14-running-the-server-long-term).

---

## 5. Checks without the page

```bash
doc model                     # facts, check, docs/system.html, opens it
doc model --check             # facts and check only; exit 1 on a problem
doc model --no-open --no-issues
doc report [--no-open] [--no-issues]
```

`docs/system.html` is the page without forms, for reading offline.
`docs/report.html` is a one-page status summary (requirements, faults, decisions).

---

## 6. Scripts and CI

`doc model --check` exits 1 when the wiring is broken, which also catches
commits from people who did not install the hook. In GitHub Actions:

```yaml
- uses: actions/setup-python@v5
  with: { python-version: "3.12" }
- run: python3 tools/doc-kit/doc.py model --check
```

The records are plain Markdown tables, and the model is two small text files
(`docs/model/model.toml`, `docs/model/<name>_arch.sysml`), so scripts can read
them directly.

---

Publishing a read-only page: **Setup → Publish a read-only page** writes
`.github/workflows/doc-kit-pages.yml`, which runs `doc model` on every push and
deploys `docs/system.html` and `docs/media/` to GitHub Pages.

Per-computer settings (the part library folders and the default one) are in
`~/.config/doc-kit/settings.json`.

---

## 7. Updating doc-kit in a project

```bash
cd path/to/doc-kit && git pull
python3 doc.py init path/to/your/project
cd path/to/your/project && doc install-hook
```

`init` replaces everything in `tools/doc-kit/` and leaves your docs untouched. Restart
`doc serve` afterwards. Projects set up with doc-kit 0.2 keep working: their
README subsystem table is taken over into `model.toml` on the first Setup
change, and an untouched 0.2 default list is cleared, so Setup starts empty.
Projects set up before 0.5 had doc-kit's files loose in `tools/`: `init` moves
them into `tools/doc-kit/` (your own files in `tools/` are left alone), updates
the hooks and the Pages workflow, and the `doc` alias must then point at
`tools/doc-kit/doc.py`.

---

## 8. What moved to the page

Earlier versions asked questions in the terminal. Each of those is now a form
on the page, writing the same files:

| Was | Now |
|---|---|
| `doc` (menu), `doc idea`, `doc bug`, `doc decision`, `doc req`, `doc fault`, `doc procedure`, `doc check`, `doc log` | **+ New** |
| `doc test ID` | **Record test** on the requirement |
| `doc update ID` | **Edit**, **Mark deleted**, **Change status** on the record |
| `doc model setup` | **Setup**: subsystems, boards, ROS2 code folders |
| writing `<name>_arch.sysml` by hand | **Edit** in the System, Electrical, Power and Mechanical views |
| editing the subsystem lists in `docs/README.md` and the issue forms | **Setup → Subsystems** |
| `doc tidy` | not needed: requirements are always written into their subsystem's section |
