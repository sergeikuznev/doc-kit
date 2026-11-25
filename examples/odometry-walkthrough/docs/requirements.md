# Example Robot requirements

Each requirement: an ID, a measurable "shall", the reason, how it is verified,
and its status. Never reuse or renumber IDs; mark dropped ones as Deleted.

**Verification methods:** T = Test, I = Inspection, A = Analysis, D = Demonstration
**Status:** Draft, Approved, Verified, Failed, Deleted

One section per subsystem, in the order of the prefix table in docs/README.md.
`doc req` adds each requirement to its section and creates the section if needed.

## SYS: Whole system

| ID | Requirement | Rationale | Method | Status | Evidence |
|---|---|---|---|---|---|
| SYS-001 | The robot shall stop all motors within 1 s of losing the operator link. | Prevents runaway when the link drops | T | Approved |  |

## NAV: Navigation and localisation

| ID | Requirement | Rationale | Method | Status | Evidence |
|---|---|---|---|---|---|
| NAV-001 | The robot shall estimate its position with less than 0.1 m error after driving a 2 m square. | Nav2 cannot reach goals reliably with worse odometry | T | Verified | 2026-11-25: 0.6 m error; left encoder connector loose, ticks dropping. logs/2026-11-25_odom_square_fail.mcap<br>2026-11-26: Max 0.08 m error over 5 runs of a 2 m square. media/2026-11-26_odom_square_pass.mp4 |
