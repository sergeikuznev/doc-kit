# Examples

## odometry-walkthrough

The files `doc` produced while adding wheel odometry to a small robot,
following the story in [docs/GUIDE.md](../docs/GUIDE.md#4-one-feature-start-to-finish):

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
