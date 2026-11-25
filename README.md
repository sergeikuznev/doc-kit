# doc-kit

**Fill-in-the-blanks engineering documentation for hardware and robotics projects.**

You run `doc`, it asks what just happened, then asks the right questions and writes
your answers into the right file with the right structure: decision records,
requirements with IDs, a fault table (FMEA), procedures, a pre-power checklist,
a weekly devlog, and GitHub issues.

It is a single Python file with no dependencies, and it never writes anything you
did not say. No AI, no guessing: you supply every word, it handles the format,
the numbering and the cross-links.

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

## Why

Documentation written upfront becomes fiction; documentation written at the end
forgets *why* things were done. The habit that works is writing a little at the
moment something happens: a decision, a test, a near miss. `doc` makes that a
30-second job, so it actually happens.

See [docs/GUIDE.md](docs/GUIDE.md) for the method behind it, and
[examples/](examples/) for what the output looks like.

## Quick start

```bash
git clone https://github.com/sergeikuznev/doc-kit.git
cd doc-kit
python3 doc.py init /path/to/your/project
```

`init` copies the templates and the tool into your project (it never overwrites
existing files) and prints the next steps:

1. Edit the subsystem list in `docs/README.md` and `.github/ISSUE_TEMPLATE/*.yml`.
2. Add the shortcut to `~/.zshrc` or `~/.bashrc`, once per computer:
   ```bash
   alias doc='python3 "$(git rev-parse --show-toplevel)/tools/doc.py"'
   ```
3. Inside your project: `doc install-hook`
4. Optional, for `doc idea` / `doc bug`: install the [GitHub CLI](https://cli.github.com) and run `gh auth login`.

## Commands

| Command | Does | Writes to |
|---|---|---|
| `doc` | Menu: "what just happened?" | |
| `doc idea` | Creates a GitHub issue from your answers | GitHub Issues |
| `doc bug` | Creates a bug report issue | GitHub Issues |
| `doc decision` | Decision record, auto-numbered | `docs/decisions/NNN-title.md` |
| `doc req` | Requirement with the next ID for its subsystem | `docs/requirements.md` |
| `doc test ID` | Test result and evidence for a requirement | `docs/requirements.md` |
| `doc fault` | Failure mode row (FM-001, ...) | `docs/fdir.md` |
| `doc procedure` | Numbered procedure | `docs/procedures/<title>.md` |
| `doc check` | Checklist line plus a dated reason | `docs/procedures/pre_power_checklist.md` |
| `doc log` | This week's devlog entry (adds to it if it exists) | `docs/devlog.md` |
| `doc update [ID]` | Change a status, text or link written earlier; requirement changes are logged | the document that holds it |
| `doc report` | Status page: what is verified, failed, untested or uncovered; opens in your browser | `docs/report.html` |
| `doc tidy` | Regroups requirements by subsystem | `docs/requirements.md` |
| `doc install-hook` | After commits with `fixes #N`, asks if a document is needed | `.git/hooks/post-commit` |

While answering:

- **Choices are menus:** ↑↓ to move, Enter to select, or start typing to filter
  (e.g. `nav` jumps to NAV). You only type free text.
- `<` goes back one question (inside a list, it removes the last line)
- `<<` opens a list of all your answers so far; pick one to change it, and the rest are kept
- At the end you choose **Write it**, **Change an answer** or **Cancel**; nothing is written before that
- Ctrl+C cancels at any point

When input is piped (scripts, CI) or on Windows, menus fall back to typing a
number or key. Set `DOC_PLAIN=1` to force that mode.

## Status report

`doc report` builds `docs/report.html` from your Markdown files and opens it:
requirement progress per subsystem, everything that needs attention (failed or
untested requirements, failure modes with no requirement, decisions still
proposed), the fault-to-requirement links, decisions, the latest devlog entry,
recent requirement changes, and open GitHub issues if the `gh` CLI is set up.
It is regenerated each time, so commit it only if you want a snapshot.
Options: `--no-open`, `--no-issues`.

## What it creates in your project

```
docs/
  README.md                 how the docs work + your subsystem list
  requirements.md           one section per subsystem, with test evidence
  fdir.md                   fault table
  devlog.md                 weekly log
  decisions/                one file per decision
  procedures/               procedures and the pre-power checklist
  icd/                      interface definitions (written by hand)
  media/                    photos and videos
.github/ISSUE_TEMPLATE/     Idea and Bug forms for the GitHub website
tools/doc.py                the tool
```

Everything is plain Markdown, so you can edit any file by hand and the tool keeps working.

## Customising

- **Subsystems for requirement IDs:** edit the `| Prefix | Subsystem |` table in
  `docs/README.md`. The tool reads it every time.
- **Subsystems for issues:** edit the `options:` list in `.github/ISSUE_TEMPLATE/idea.yml`
  and `bug.yml`. `doc idea` and `doc bug` read it too, so the web form and the CLI match.
- **Templates:** change the files in `docs/`; the tool only relies on the table headers.

## Using it in a team

The tool and templates live in the project repo, so teammates get them by cloning.
Each person adds the `doc` shortcut and runs `doc install-hook` once (git hooks
are not shared through the repo).

## Updating

Pull the latest doc-kit and run `python3 doc.py init /path/to/your/project` again.
It replaces `tools/doc.py` and leaves all your existing docs untouched.

## Requirements

- Python 3.8 or newer, git
- Optional: [GitHub CLI](https://cli.github.com) for `doc idea` and `doc bug`
- macOS and Linux. Windows is untested (the commit hook needs a Unix shell).

## License

MIT, see [LICENSE](LICENSE).
