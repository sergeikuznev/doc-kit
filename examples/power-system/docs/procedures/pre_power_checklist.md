# Example Robot pre-power checklist

Run this before powering up after any hardware change.
Every line exists because something broke, or nearly did. Add lines with: doc check

## Wiring
- [ ] No loose or exposed conductors near the chassis or moving parts.
- [ ] Battery packs balance-charged to 4.2 V/cell before every test session

## Electrical checks (multimeter, power disconnected)
- [ ] No short between supply + and GND.

## First power-up
- [ ] Power through a current-limited bench supply first if possible.
- [ ] Emergency stop cuts motor power.

## History
| Date | Line added | Why |
|---|---|---|
| 2026-11-26 | Battery packs balance-charged to 4.2 V/cell before every test session | PWR-001 runtime test failed at 22 min because the pack was at storage charge |
