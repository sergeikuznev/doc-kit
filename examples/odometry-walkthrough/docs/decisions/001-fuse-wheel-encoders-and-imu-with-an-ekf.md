# 001. Fuse wheel encoders and IMU with an EKF

- **Date:** 2026-11-25
- **Status:** Accepted
- **Related:** #3

## Context
- Nav2 needs an odometry source to navigate
- Wheels slip on smooth floors, so encoders alone drift when turning
- The robot already has an IMU on the microcontroller

## Options
1. **Encoders only**
   - Pro: Simplest, no extra package
   - Con: Heading drifts when wheels slip
2. **Encoders + IMU fused with robot_localization EKF**
   - Pro: IMU heading does not drift with wheel slip
   - Pro: Standard ROS2 package, well documented
   - Con: More configuration; covariances need tuning

## Decision
Fuse wheel encoders and IMU with the robot_localization EKF for odometry.

**Deciding factor:** Wheel slip on the lab floor makes encoder-only heading unusable

## Consequences
- Need to publish IMU data from the microcontroller
- EKF covariances must be tuned; revisit if odometry drifts more than expected
