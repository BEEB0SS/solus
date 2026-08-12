# Elegoo V4 Obstacle Avoidance Robot

PID-based obstacle avoidance using an HC-SR04 ultrasonic sensor and TB6612FNG motor driver.

This folder is the "project source" that Solus syncs as a code source (see `tests/test_demo_flow.py`). `src/obstacle_avoidance.ino` intentionally contains the demo bug — bad PID gains (`KP=50, KD=0`) that cause violent oscillation in front of obstacles.

The flash-demo pair lives in `../arduino-sketches/`:

- `buggy/buggy.ino` — same buggy firmware, flashed to reproduce the fault live
- `fixed/fixed.ino` — corrected gains (`KP=2, KD=0.5`) plus derivative damping, flashed after the agent's diagnosis
