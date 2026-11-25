# Example Robot requirements

Each requirement: an ID, a measurable "shall", the reason, how it is verified,
and its status. Never reuse or renumber IDs; mark dropped ones as Deleted.

**Verification methods:** T = Test, I = Inspection, A = Analysis, D = Demonstration
**Status:** Draft, Approved, Verified, Failed, Deleted

One section per subsystem, in the order of the prefix table in docs/README.md.
`doc req` adds each requirement to its section and creates the section if needed.

## PWR: Power

| ID | Requirement | Rationale | Method | Status | Evidence |
|---|---|---|---|---|---|
| PWR-001 | The robot shall drive for at least 30 min on flat ground from one full battery charge. | Test sessions need 30 min; this is why LiPo was chosen (decision 001) | T | Verified | 2026-11-26: Only 22 min; pack started at 3.85 V/cell (storage charge, not full). logs/2026-11-26_runtime_run1.mcap<br>2026-11-26: 34, 33 and 35 min over 3 runs from a full balance charge. media/2026-11-26_runtime_runs.mp4 |
| PWR-002 | The robot shall stop all motors within 1 s when any battery cell drops below 3.3 V under load. | Over-discharge permanently damages LiPo cells (decision 001) | T | Verified | 2026-11-26: Bench supply ramped down: motors stopped at 3.29 V/cell, 0.4 s after crossing. logs/2026-11-26_cutoff_bench.mcap |

## Change log

| Date | ID | Change |
|---|---|---|
| 2026-11-26 | PWR-002 | Requirement: was "The robot shall stop all motors within 1 s when any battery cell drops below 3.0 V." |
