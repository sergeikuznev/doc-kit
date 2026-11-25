# 001. Use a 3S LiPo battery instead of NiMH

- **Date:** 2026-11-26
- **Status:** Accepted
- **Related:** #12

## Context
- The robot must drive for at least 30 min per test session
- The mass budget for the battery is about 400 g
- Motors draw up to 6 A when stalled

## Options
1. **NiMH pack**
   - Pro: Robust chemistry, hard to damage
   - Pro: Simple charging
   - Con: About twice as heavy for the same energy
   - Con: Voltage drops steadily during discharge
2. **3S LiPo pack**
   - Pro: Highest energy per kg: 30+ min fits in the mass budget
   - Pro: Flat voltage curve under load
   - Con: Permanently damaged if a cell is over-discharged
   - Con: Needs a balance charger and fire-safe storage

## Decision
Use a 3S LiPo pack, protected by a low-voltage motor cutoff.

**Deciding factor:** Only LiPo fits 30 min of driving into the 400 g mass budget

## Consequences
- Need a per-cell low-voltage cutoff (becomes PWR-002)
- Need a balance charger and a LiPo-safe storage bag
- Revisit if runtime requirements grow beyond what 400 g of LiPo can deliver
