# doc-kit

**An event-driven, docs-as-code engineering record with built-in traceability,
for hardware and robotics projects.**

doc-kit captures ideas, decisions, requirements, failure modes and test evidence
at the moment they happen, links them together, and reports what is verified,
failing or not yet covered. It is a lightweight version of the systems
engineering loop used in aerospace: requirements, design decisions, FMEA and
verification, scaled down for one person or a small team.

You run `doc`, it asks what just happened, then asks the right questions and writes
your answers into the right file with the right structure. It is a single Python
file with no dependencies, and it never writes anything you did not say. No AI,
no guessing: you supply every word, it handles the format, the numbering and the
cross-links.

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

## The loop: Decide, Verify, Learn

Like FDIR (Fault Detection, Isolation and Recovery) names a loop of functions,
doc-kit implements a loop. Each stage has a trigger in your work and a command:

| Stage | What it does | Trigger | Command |
|---|---|---|---|
| **Capture** | Record an idea or problem before it is lost | You notice something | `doc idea`, `doc bug` |
| **Decide** | Choose between options and record why | You compare alternatives | `doc decision` |
| **Commit** | Turn a choice into a measurable promise | You decide to build it | `doc req` |
| **Anticipate** | Plan how failures are detected and handled | You ask "what if it breaks?" | `doc fault` |
| **Verify** | Prove the promise with evidence | You test it | `doc test` |
| **Learn** | Turn incidents and experience into rules | Something breaks, or the week ends | `doc check`, `doc procedure`, `doc log` |

Around the loop: **Trace** (`doc report` shows how faults, requirements, evidence
and issues connect) and **Revise** (`doc update` changes earlier entries, and
requirement changes are logged).

The core is **Decide, Verify, Learn**: reasons are recorded, claims are proven,
and mistakes turn into rules. That is what separates it from a notes folder.

## Why

Documentation written upfront becomes fiction; documentation written at the end
forgets *why* things were done. The habit that works is writing a little at the
moment something happens: a decision, a test, a near miss. `doc` makes that a
30-second job, so it actually happens.

It builds on three established practices:

- **Docs-as-code:** documentation in plain text, in the repo, versioned with git
  and reviewed like code.
- **Requirements traceability:** every requirement linked to its rationale, the
  failures it covers, and the evidence that it is met.
- **Lightweight systems engineering:** the cycle of requirements, design
  decisions, failure analysis and verification, without the heavyweight tools.

**New to this? Read the [handbook](docs/HANDBOOK.md).** It explains each record
(issue, decision, requirement, fault, evidence, procedure, checklist, devlog):
when to write one, what a good one looks like next to a weak one, how they
connect, and [how to use the record afterwards](docs/HANDBOOK.md#14-using-the-record):
weekly reviews, debugging, design reviews, onboarding, reusing it on the next
robot, and your portfolio. [examples/](examples/) shows real output.

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
| `doc model setup` | Points the system model at your `.ioc` files and ROS2 code (once) | `docs/model/model.toml`, starter arch file |
| `doc model` | Rebuilds the facts, checks your architecture against them, opens the system map | `docs/model/<name>_facts.sysml`, `docs/system.html` |
| `doc serve` | Serves the system map with forms; pulls, rebuilds, commits and pushes | `http://127.0.0.1:8765` (share with `tailscale serve --bg 8765`) |
| `doc tidy` | Regroups requirements by subsystem | `docs/requirements.md` |
| `doc install-hook` | After commits with `fixes #N`, asks if a document is needed; before each commit, checks the model | `.git/hooks/post-commit`, `.git/hooks/pre-commit` |

While answering:

- **Choices are menus:** ↑↓ to move, Enter to select, or start typing to filter
  (e.g. `nav` jumps to NAV). You only type free text.
- **A preview pane under every menu** shows the highlighted item in full: the
  whole requirement with its evidence, every column of a fault row, your full
  answer in the `<<` list. Rows stay one line each.
- `<` goes back one question (inside a list, it removes the last line)
- `<<` opens a list of all your answers so far; pick one to change it, and the rest are kept
- After `<` or `<<` your previous answer comes back **filled in**, so you fix a typo
  instead of retyping. Lists come back line by line. Editing keys: ←→, Option+←→
  (word), Home/End or Ctrl+A/Ctrl+E, Ctrl+U (clear line), Ctrl+W (delete word)
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

## System model

`doc model` builds one model of the robot from files you already keep, and
draws it as an interactive page (`docs/system.html`):

| Comes from | What | Written by |
|---|---|---|
| `.ioc` files | boards, peripherals, pins, peripheral settings, FreeRTOS tasks, clocks | CubeMX |
| ROS2 / micro-ROS code | nodes, topics, message types (read from the code; the robot can be off) | you, in code |
| `docs/requirements.md`, `fdir.md`, `decisions/` | requirements, faults, decisions | `doc req`, `doc fault`, `doc decision` |
| `docs/model/<name>_arch.sysml` | subsystems, modules, wiring, which computer runs which node | you, in SysML v2 text |

The first four are facts: `doc model` regenerates `<name>_facts.sysml` from
them, and you never edit it. The arch file is the only thing you write. Every
`connect` line is checked against the facts, so a pin renamed in CubeMX or a
bus wired to a GPIO stops the commit (pre-commit hook) instead of silently
leaving a wrong diagram. Anything a scanner cannot read for certain (a topic
name built at runtime) is listed as unknown, never guessed.

The page has views (System, Electrical, Power, Mechanical, Software), a
generated interface table between subsystems, requirements, faults and
decisions linked to the parts they belong to, and the gaps a design review
would ask about. Layout is automatic (ELK, bundled in `vendor/`, EPL-2.0).
The page also shows your GitHub issues (via `gh`), your docs and procedures,
doc-kit's own guides, and everything in `docs/media/`: a photo or log whose
file name appears in a requirement's evidence shows up on that requirement.
See [the handbook](docs/HANDBOOK.md#15-the-system-model) for how to write the arch file.

### Live, with forms: `doc serve`

`doc serve` runs a small server on this machine (127.0.0.1 only). Share it with
your own devices through Tailscale: `tailscale serve --bg 8765`. While it runs it:

- pulls from GitHub every minute (fast-forward only) and rebuilds when anything changed;
- refreshes issues every 5 minutes;
- shows a *The project changed · Reload* bar in open pages; reloading keeps your view and selection;
- accepts forms: idea, bug, requirement, test result (with photo / video / log upload), fault,
  decision, and edits (status, text, mark deleted, supersede). Each form shows a preview of
  exactly what will be written, then writes the same files the terminal commands write,
  commits and pushes (`--no-push` to keep commits local).

It refuses to write a file that has uncommitted changes in its working copy, so it never
commits half of your own edit. Generated files and other tools' files (`.ioc`, code,
`*_facts.sysml`) are never written from the page.

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
  media/                    photos, videos, logs (shown in the system map)
  model/                    created by doc model setup: model.toml, <name>_arch.sysml (yours),
                            <name>_facts.sysml (generated)
  report.html, system.html  generated pages
.github/ISSUE_TEMPLATE/     Idea and Bug forms for the GitHub website
tools/doc.py                the tool
tools/docmodel.py, docmodel_page.html, docserve.py, vendor/   system map and server
tools/guides/               README and handbook, shown in the system map's Docs section
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
It replaces everything in `tools/` and leaves all your existing docs untouched.
Then run `doc install-hook` once more if the new version added hooks.

## Requirements

- Python 3.8 or newer, git; `doc model` and `doc serve` need Python 3.11 or newer
- Optional: [GitHub CLI](https://cli.github.com) for `doc idea`, `doc bug` and issues in the system map
- Optional: [Tailscale](https://tailscale.com) to open `doc serve` from your phone and other devices
- macOS and Linux. Windows is untested (the commit hook needs a Unix shell).

## License

MIT, see [LICENSE](LICENSE). `vendor/elk.bundled.js` is
[ELK](https://github.com/kieler/elkjs) (Eclipse Public License 2.0), see `vendor/LICENSE-elkjs.md`.
