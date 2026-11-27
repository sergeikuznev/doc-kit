# Odometry example documentation

Records are written **when something happens**, not filled in upfront.
Run `doc serve` and open the page: every record below has a form there (**+ New**, or the
buttons on each card), and the page commits and pushes what you write.
New to this? The page has the guides under **Docs › How to use doc-kit**.

| When this happens | Write | On the page | File |
|---|---|---|---|
| You get an idea | An issue | + New › Idea | GitHub Issues |
| Something behaves wrong | An issue | + New › Bug | GitHub Issues |
| You choose between options | A decision record | + New › Decision | `decisions/NNN-title.md` |
| You commit to building something | A requirement with an ID | + New › Requirement | `requirements.md` |
| You ask "what if this breaks?" | A row in the fault table | + New › Fault | `fdir.md` |
| You test a requirement | Result and evidence | Record test (on the requirement) | `requirements.md` |
| You assemble something with steps | A procedure | + New › Procedure | `procedures/` |
| Something breaks or nearly breaks | A checklist line | + New › Checklist line | `procedures/pre_power_checklist.md` |
| Something written earlier changed | The new status, text or link | Edit (on the record) | where it was written |
| End of the week | A devlog entry | + New › Devlog | `devlog.md` |
| You add a module or a wire | Parts and connections | System views › Edit | `model/Odometry example_arch.sysml` |

## Subsystems

Subsystems are the boxes of the system diagram and the prefixes of requirement IDs
(`CTRL-001` belongs to `CTRL`). Add and rename them on the page under **Setup**;
this table is written from there.

<!-- doc-kit:subsystems (edit on the page: Setup) -->
| Prefix | Subsystem |
|---|---|
| SYS | Whole system (requirements only) |
| NAV | Navigation and localisation |
| SENS | Sensors and perception |
| MOT | Motors and actuators |
<!-- /doc-kit:subsystems -->

Fault table rows use `FM-001`, `FM-002`, ... (failure mode).

## Naming

- Lowercase, underscores, no spaces: `motor_mounting.md`
- Media: `YYYY-MM-DD_subject_detail.jpg` (uploads from the page are named this way)
- Decision records are numbered and never renumbered: `001-...`, `002-...`
- Requirement IDs are never reused; a dropped requirement is marked Deleted
