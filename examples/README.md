# Examples

Two small projects, both produced by running `doc` and typing the answers.
The [handbook](../docs/HANDBOOK.md) walks through them.

## power-system

Choosing a battery and proving it works: a decision that creates two
requirements, a fault that one of them covers, a failed test that becomes a
checklist line, a corrected requirement in the change log, and the status page.

| Step | Command | Result |
|---|---|---|
| Choose LiPo over NiMH, record why | `doc decision` | [decisions/001-...](power-system/docs/decisions/001-use-a-3s-lipo-battery-instead-of-nimh.md) |
| Promise runtime, and protection for LiPo's weakness | `doc req` ×2 | PWR-001, PWR-002 in [requirements.md](power-system/docs/requirements.md) |
| Plan for over-discharge and for brownout | `doc fault` ×2 | FM-001 (covered by PWR-002), FM-002 (not yet covered) in [fdir.md](power-system/docs/fdir.md) |
| Cutoff of 3.0 V had no margin under load | `doc update PWR-002` | 3.3 V, old text kept in the change log |
| First runtime test fails: pack not fully charged | `doc test PWR-001` | Failed, with evidence |
| Make sure it never happens again | `doc check` | Line in [pre_power_checklist.md](power-system/docs/procedures/pre_power_checklist.md) |
| Retest, and test the cutoff | `doc test` | Both Verified; the failure stays in the record |
| Save the charging know-how | `doc procedure` | [charging_a_lipo_pack.md](power-system/docs/procedures/charging_a_lipo_pack.md) |
| End of the week | `doc log` | [devlog.md](power-system/docs/devlog.md) |
| The big picture | `doc report` | [report.html](power-system/docs/report.html) (download and open in a browser) |

## odometry-walkthrough

The files `doc` produced while adding wheel odometry to a small robot,
following the story in [the handbook](../docs/HANDBOOK.md#one-feature-start-to-finish):

| Step | Command | Result |
|---|---|---|
| Choose encoders + IMU fusion | `doc decision` | [decisions/001-...](odometry-walkthrough/docs/decisions/001-fuse-wheel-encoders-and-imu-with-an-ekf.md) |
| Set a measurable target | `doc req` | NAV-001 in [requirements.md](odometry-walkthrough/docs/requirements.md) |
| Plan for encoder failure | `doc fault` | FM-001 in [fdir.md](odometry-walkthrough/docs/fdir.md) |
| First test fails (loose connector) | `doc test` | NAV-001 marked Failed, with evidence |
| Make sure it never happens again | `doc check` | New line in [pre_power_checklist.md](odometry-walkthrough/docs/procedures/pre_power_checklist.md) |
| Retest after the fix | `doc test NAV-001` | NAV-001 Verified; both results kept |
| Save the calibration know-how | `doc procedure` | [calibrating_the_imu.md](odometry-walkthrough/docs/procedures/calibrating_the_imu.md) |
| End of the week | `doc log` | [devlog.md](odometry-walkthrough/docs/devlog.md) |

Every word in these files was typed as an answer; the tool only added the structure,
IDs, dates and links.
