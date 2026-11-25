# Example Robot pre-power checklist

Run this before powering up after any hardware change.
Every line exists because something broke, or nearly did. Add lines with: doc check

## Wiring
- [ ] No loose or exposed conductors near the chassis or moving parts.
- [ ] Encoder connectors fully seated and secured with tape or glue

## Electrical checks (multimeter, power disconnected)
- [ ] No short between supply + and GND.

## First power-up
- [ ] Power through a current-limited bench supply first if possible.
- [ ] Emergency stop cuts motor power.

## History
| Date | Line added | Why |
|---|---|---|
| 2026-11-25 | Encoder connectors fully seated and secured with tape or glue | Left encoder came loose during NAV-001 test, 0.6 m odometry error |
