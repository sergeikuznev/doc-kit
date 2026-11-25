# Example Robot fault table (FDIR / FMEA)

One row per thing that can go wrong. FDIR = Fault Detection, Isolation and Recovery.

- **Response:** make it safe now (stop, isolate). **Recovery:** get back to normal.
- **Severity:** 1 = annoying, 2 = mission degraded, 3 = mission lost, 4 = hardware damage.
  If one failure can lead to several outcomes, rate the worst credible one.
- **Req:** the requirement that promises this failure is handled.

| ID | Failure | Effect | Detection | Isolation / response | Recovery | Sev | Req |
|---|---|---|---|---|---|---|---|
| FM-001 | Battery cell over-discharged | Permanent cell damage; pack may swell | Per-cell voltage from the balance lead below threshold | Stop motors, set low-battery flag | Recharge on a balance charger; inspect the pack for swelling before reuse | 4 | PWR-002 |
| FM-002 | Voltage sag during motor stall resets the microcontroller | Controller reboots mid-drive; motors uncontrolled for about 200 ms | Reset-cause register reports brownout at boot; logged voltage dip | Limit motor current when a stall is detected | Resume after reboot; operator checks the log | 3 |  |
