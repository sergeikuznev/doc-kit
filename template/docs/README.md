# {{PROJECT}} documentation

Documents are written **when something happens**, not filled in upfront.
`tools/doc.py` asks the questions and writes the files; see the commands below.

| When this happens | Write | Command | Where |
|---|---|---|---|
| You get an idea | An issue | `doc idea` | GitHub Issues |
| Something behaves wrong | An issue | `doc bug` | GitHub Issues |
| You choose between options | A decision record | `doc decision` | `decisions/NNN-title.md` |
| You commit to building something | A requirement with an ID | `doc req` | `requirements.md` |
| You ask "what if this breaks?" | A row in the fault table | `doc fault` | `fdir.md` |
| You define how two parts talk | An interface definition | (by hand) | `icd/` |
| You assemble something with steps | A procedure | `doc procedure` | `procedures/` |
| Something breaks or nearly breaks | A checklist line | `doc check` | `procedures/pre_power_checklist.md` |
| You test a requirement | Result and evidence | `doc test ID` | `requirements.md` |
| End of the week | A devlog entry | `doc log` | `devlog.md` |

## Naming

- Lowercase, underscores, no spaces: `motor_mounting.md`
- Media: `YYYY-MM-DD_subject_detail.jpg`
- Decision records are numbered and never renumbered: `001-...`, `002-...`

## Requirement ID prefixes

`tools/doc.py` reads this table. Edit the rows to match your project's subsystems.
Requirements are grouped in `requirements.md` in this order.

| Prefix | Subsystem |
|---|---|
| SYS | Whole system |
| COMM | Communications |
| PWR | Power |
| MOT | Motors and actuators |
| SENS | Sensors and perception |
| SW | Software |
| MECH | Mechanical |
| FDIR | Fault detection, isolation and recovery |

Fault table rows use `FM-001`, `FM-002`, ... (failure mode).

## The doc tool

```bash
doc              # menu: "what just happened?"
doc idea / bug   # create a GitHub issue (needs the gh CLI)
doc decision     # new decision record (auto-numbered)
doc req          # new requirement (next ID for the subsystem)
doc test ID      # record a test result and evidence
doc fault        # new row in fdir.md
doc procedure    # new procedure file
doc check        # new pre-power checklist line, with history
doc log          # devlog entry for this week
doc tidy         # regroup requirements.md by subsystem
doc install-hook # after commits with "fixes #N", ask if a document is needed
```

Every command shows a preview before writing. Type `<` to go back one question,
`<<` to jump to any earlier answer. Ctrl+C cancels without writing.
