# Examples

Two small projects. Every word in them was typed into the record forms; the tool only
added the structure, IDs, dates and links. (They were made with the terminal
forms of doc-kit 0.2; the page writes the same files.)
The [handbook](../docs/HANDBOOK.md) walks through them.

## power-system

Choosing a battery and proving it works: a decision that creates two
requirements, a fault that one of them covers, a failed test that becomes a
checklist line, a corrected requirement in the change log, and the status page.

| Step | On the page | Result |
|---|---|---|
| Choose LiPo over NiMH, record why | + New → Decision | [decisions/001-...](power-system/docs/decisions/001-use-a-3s-lipo-battery-instead-of-nimh.md) |
| Promise runtime, and protection for LiPo's weakness | + New → Requirement ×2 | PWR-001, PWR-002 in [requirements.md](power-system/docs/requirements.md) |
| Plan for over-discharge and for brownout | + New → Fault ×2 | FM-001 (covered by PWR-002), FM-002 (not yet covered) in [fdir.md](power-system/docs/fdir.md) |
| Cutoff of 3.0 V had no margin under load | Edit on PWR-002 | 3.3 V, old text kept in the change log |
| First runtime test fails: pack not fully charged | Record test on PWR-001 | Failed, with evidence |
| Make sure it never happens again | + New → Checklist line | Line in [pre_power_checklist.md](power-system/docs/procedures/pre_power_checklist.md) |
| Retest, and test the cutoff | Record test | Both Verified; the failure stays in the record |
| Save the charging know-how | + New → Procedure | [charging_a_lipo_pack.md](power-system/docs/procedures/charging_a_lipo_pack.md) |
| End of the week | + New → Devlog | [devlog.md](power-system/docs/devlog.md) |
| The big picture | Overview (or `doc report` for a file) | [report.html](power-system/docs/report.html) (download and open in a browser) |

## odometry-walkthrough

The files written while adding wheel odometry to a small robot,
following the story in [the handbook](../docs/HANDBOOK.md#one-feature-start-to-finish):

| Step | On the page | Result |
|---|---|---|
| Choose encoders + IMU fusion | + New → Decision | [decisions/001-...](odometry-walkthrough/docs/decisions/001-fuse-wheel-encoders-and-imu-with-an-ekf.md) |
| Set a measurable target | + New → Requirement | NAV-001 in [requirements.md](odometry-walkthrough/docs/requirements.md) |
| Plan for encoder failure | + New → Fault | FM-001 in [fdir.md](odometry-walkthrough/docs/fdir.md) |
| First test fails (loose connector) | Record test | NAV-001 marked Failed, with evidence |
| Make sure it never happens again | + New → Checklist line | New line in [pre_power_checklist.md](odometry-walkthrough/docs/procedures/pre_power_checklist.md) |
| Retest after the fix | Record test on NAV-001 | NAV-001 Verified; both results kept |
| Save the calibration know-how | + New → Procedure | [calibrating_the_imu.md](odometry-walkthrough/docs/procedures/calibrating_the_imu.md) |
| End of the week | + New → Devlog | [devlog.md](odometry-walkthrough/docs/devlog.md) |

