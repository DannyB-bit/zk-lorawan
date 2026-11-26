# RF Compliance & ADR Calibration — Frontier Drill (Dan 2026-11-24 order)

## 1. FCC posture (US915, 902–928 MHz ISM band)

| Parameter | Value | Basis |
|---|---|---|
| Carrier | 903.9 MHz | inside 902–928 MHz ISM band |
| Modulation | LoRa CSS, BW 125 kHz, CR 4/5, explicit header, CRC on | — |
| TX power | **14 dBm = 25 mW** (hard cap 20 dBm enforced in `fire_frames.sh`) | far below FCC Part 15.247 30 dBm (1 W) ceiling |
| Duty cycle (measured) | ~14.5 s airtime per 12-frame issue burst at SF9; worst observed solution burst 101 frames = 122 s | ≈0.02–0.04 % hourly; US915 has no legal duty-cycle cap (unlike EU868), kept low by design |
| Emissions | short packet bursts only; no continuous carrier, no jamming, fixed experimental channel | — |

**Honest status:** experimental, non-certified, low-power point-to-point research link.
A *production* US915 deployment must use FHSS channel hopping across the LoRaWAN
64-channel uplink plan (903.9 + 0.2·n MHz) or ≥500 kHz DTS operation to fit Part 15.247
system categories. FHSS hop sequencing is on the roadmap (also improves interference
resilience); current single-channel operation is deliberately minimal-power/minimal-airtime.

## 2. Measured LoRa airtime per 245 B sealed chirp (BW125, CR4/5)

| SF | airtime/frame | 12-frame issue | 101-frame solution |
|---|---|---|---|
| 7 | 0.384 s | 4.6 s | 38.8 s |
| 8 | 0.676 s | 8.1 s | 68.3 s |
| 9 | 1.209 s | 14.5 s | 122.1 s |
| 10 | 2.214 s | 26.6 s | 223.6 s |
| 11 | 4.837 s | 58.0 s | 488.5 s |
| 12 | 8.856 s | 106.3 s | 894.5 s |

## 3. ADR speed calibration (joint A↔B experiment)

Measured link: near-100 % unique-frame capture at SF9 over the A↔B lab link
(20/22, 33/34, 36/38 frames), strong SNR → large link margin. **SF7 cuts airtime 3.15×**
with no range requirement change for this link. Both HAL RX receivers run
LoRaWAN-like multi-SF mode (`-m 0`), so SF7 is audible with **no receiver changes**.

Protocol (agreed over fast bus):
1. Both sides switch fire scripts to `SF=7` (power unchanged 14 dBm).
2. Validate over the next 3 issues: unique-frame capture ≥99 % per leg,
   sha-verified reassembly unchanged.
3. **Auto-revert to SF9** on any leg dropping below 95 % capture (log the revert).
4. Inter-frame `GAP` stays 3 s initially; may drop to 2 s if capture holds.

Expected effect: solution bursts (the long legs) go from ~8–17 min wall-clock to
~3–6 min; issue legs from ~2 min to <1 min. The dominant round cost (B solve time,
~100 min median) is untouched — ADR removes radio wait, not thinking time.

## 4. Guardrails in code
- `fire_frames.sh`: refuses POW > 20 dBm or SF outside 7–12 (`FCC_GUARD`), logs
  `sf/pow_dbm/burst_airtime_s/hourly_duty_pct_if_one_burst` on every `FIRE_DONE`.
- All RF parameters remain in every attestation JSON anchored on-chain.
