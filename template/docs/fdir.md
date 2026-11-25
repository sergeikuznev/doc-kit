# {{PROJECT}} fault table (FDIR / FMEA)

One row per thing that can go wrong. FDIR = Fault Detection, Isolation and Recovery.

- **Response:** make it safe now (stop, isolate). **Recovery:** get back to normal.
- **Severity:** 1 = annoying, 2 = mission degraded, 3 = mission lost, 4 = hardware damage.
  If one failure can lead to several outcomes, rate the worst credible one.
- **Req:** the requirement that promises this failure is handled.

| ID | Failure | Effect | Detection | Isolation / response | Recovery | Sev | Req |
|---|---|---|---|---|---|---|---|
