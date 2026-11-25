# The method behind doc-kit

A short guide to documenting a hardware project so it stays understandable to
you in six months, to teammates, and to anyone reviewing your work.

## 1. The one rule

**Write a document at the moment something happens in your work.**
Not upfront, not at the end.

- Upfront documents become fiction: they describe a system you have not built yet.
- End-of-project documents are incomplete: you remember what you chose, but not why.
- Event-driven documents are cheap and accurate: 2 to 5 minutes each, while the details are fresh.

An empty template is fine. It is a slot waiting for the moment it is needed.

## 2. When to write what

| When this happens | You write | Where |
|---|---|---|
| You get an idea | An issue | GitHub Issues |
| You choose between options | A decision record | `docs/decisions/` |
| You commit to building something | A requirement with an ID | `docs/requirements.md` |
| You ask "what if this breaks?" | A row in the fault table | `docs/fdir.md` |
| You define how two parts talk | An interface definition | `docs/icd/` |
| You write the code | A commit linked to the issue | Git history |
| You test a requirement | Result and evidence | `docs/requirements.md` |
| You assemble something with steps | A procedure | `docs/procedures/` |
| Something breaks or nearly breaks | A checklist line | `docs/procedures/pre_power_checklist.md` |
| End of the week | A devlog entry | `docs/devlog.md` |

The first seven rows usually happen in order for each feature. The rest can happen any time.

An idea moves through four stages:

| Stage | Lives in | Means |
|---|---|---|
| Idea | Issue | Maybe. Cheap to write, cheap to reject. |
| Decision | Decision record | We compared options and chose one. |
| Requirement | `requirements.md` | We are doing it, and here is how we will know it works. |
| Done | Closed issue + evidence | Built, tested, proven. |

## 3. The documents

### Issue
Capture an idea or a bug in 30 seconds so it is not lost. Label it by type
(idea, bug), subsystem and priority (must, should, could). GitHub numbers issues
per repository (#1, #2, ...); use that number to link decisions, requirements and
commits back to it.

### Decision record
Explains *why* something is the way it is. Write one when you compared real
options, hesitated, or the choice is expensive to undo.

- **Title states the decision**: "Use ROS2 Humble on all machines", not "ROS2 version".
- **Context**: the problem and constraints, as facts.
- **Options**: two to four, each with honest pros and cons (optional for simple choices).
- **Decision** and the **deciding factor**: the one reason that tipped it.
- **Consequences**: what gets easier, harder, and when to revisit.

Never edit an accepted record to change the decision: write a new one that
supersedes it. The trail of changed minds is valuable.

### Requirement
A promise with a number in it, written so you can check later whether you kept it.

> **NAV-001:** The robot **shall** estimate its position with less than **0.1 m** error after driving a 2 m square.

- Use "shall" and something measurable. "Should be accurate" cannot be tested.
- **Verification method**: Test, Inspection, Analysis or Demonstration.
- **Evidence**: what you measured and where the proof is (video, log, plot).
  A requirement with no evidence is a promise not yet proven.
- IDs use a subsystem prefix and are never reused or renumbered.

### Fault table (FDIR / FMEA)
One row per thing that can go wrong.

| Column | Meaning |
|---|---|
| Failure | What fails ("encoder stops sending ticks") |
| Effect | What that does to the system or mission |
| Detection | How you notice ("power applied, zero ticks for 0.5 s") |
| Response | Make it safe now: stop, isolate. Does not fix the cause. |
| Recovery | Get back to normal, automatically or by a person |
| Severity | 1 annoying, 2 degraded, 3 mission lost, 4 hardware damage |
| Req | The requirement that promises this failure is handled |

If the same cause has different effects depending on which part fails, write
separate rows. If one row can lead to several outcomes, rate the worst credible one.

### Interface definition (ICD)
The contract between two parts that must agree: a packet format, a pinout, a
topic list. Include a version number and a change log. Change the ICD first,
then the code on both sides.

### Procedure
Steps you would otherwise forget or do wrong: one action per numbered step, plus
warnings for anything that breaks if skipped.

### Checklist
Every line exists because something broke or nearly did. Add one line, with the
date and the reason, each time that happens.

### Devlog
Ten minutes a week: done, broke or learned, next. Mention IDs so entries link to
the detail. It is the most readable record of how the project evolved.

## 4. One feature, start to finish

| Step | You do | You write |
|---|---|---|
| Idea | Notice the robot cannot tell how far it moved | Issue #3 "Odometry from encoders + IMU" |
| Decide | Compare encoders only vs. encoders fused with IMU | `decisions/001-fuse-encoders-and-imu.md` |
| Commit | Decide to build it | NAV-001 in `requirements.md` |
| Faults | Ask what happens if an encoder stops | FM-001 in `fdir.md` |
| Build | Write the code | `feat(nav): add odometry, fixes #3` |
| Test | Drive a square: 0.6 m error, loose connector | NAV-001 Failed + checklist line |
| Fix and retest | Secure connector: 0.08 m error | NAV-001 Verified, evidence added |
| Procedure | Calibration took an hour to figure out | `procedures/calibrating_the_imu.md` |
| Week ends | | Devlog entry |

One feature touched every document, a few minutes each, with no separate
documentation day. See [../examples/](../examples/) for the resulting files.

## 5. Habits

- **Close the loop:** when you close an issue, ask whether it created a decision,
  requirement or procedure. `doc install-hook` asks you automatically.
- **Commit messages:** `type(area): what changed (#issue)`, with types
  `feat`, `fix`, `docs`, `refactor`, `chore`.
- **Names:** lowercase, underscores, no spaces. Media starts with the date.
- **Do not commit build outputs or large binaries:** use `.gitignore`, and GitHub
  Releases for files over a few MB.

## 6. Start small

| Phase | Set up |
|---|---|
| Day one | Issues, decisions, procedures |
| When building safety-critical features | Requirements, fault table, ICDs |
| Every week from the start | Devlog |
| More than ~100 requirements, or a team with formal reviews | Consider a dedicated requirements tool such as StrictDoc or Doorstop |

## 7. How this maps to industry

| Here | Small company | Aerospace / large company |
|---|---|---|
| GitHub Issues | Jira, Linear | Jira |
| `requirements.md` | Wiki or Markdown | DOORS, Jama, Polarion |
| Decision records | Markdown, Confluence | Trade studies, design review minutes |
| `fdir.md` | Spreadsheet | Formal FMEA/FMECA, reliability sign-off |
| Checklist entries | Bug tickets | Nonconformance reports |

The tools differ; the habits are the same: measurable requirements, recorded
reasons, planning for failure, and evidence for every claim.
