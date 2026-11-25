# Procedure: calibrating the IMU

- **Applies to:** IMU, NAV-001
- **Time:** 10 min
- **Last updated:** 2026-11-25

## You need
- Flat level surface
- Laptop with ROS2 running

## Steps
1. Place the robot on a flat surface, motors off
2. Run the calibration node and keep the robot still for 30 s
3. Rotate the robot slowly through 360 degrees
4. Check that yaw drift is under 1 degree per minute

> **Warning:** Do not touch the robot during the 30 s still phase
