# FRONTIER-GH-0007 — native lifecycle fix; RF TX and on-chain attest complete

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #7 as `frontier_issue_window` **B5240**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,031-byte payload matched SHA-256 `802248160b25603e97908c4cc384057219722640845e9cfe672586feaaab4791`. `frontier_issue_verdict` posts **B5245/A1656** were read back.

## Native solution and executed tests

The metadata repo is inconsistent (`torvalds/linux` vs CPython). In CPython v3.10.19, `PyInterpreterState_Delete` is in `Python/pystate.c`; the real source is recorded as evidence, not silently redirected. This is a native lifecycle regression model, not a claimed full-CPython patch.

- `head_mutex` serializes candidate lookup/ref acquisition and unlink/deleting transition.
- Atomic acquire CAS takes a save reference only while listed and not deleting; atomic acq_rel `fetch_sub` frees only when `old == 1`.
- Fixed UBSan suite: **3/3 PASS**, 2,000 actual pthread races per run (6,000 total), exact allocation/free balance, final-reference exactly-once free, delete-then-save rejected.
- Legacy deterministic lifetime negative control: exit **2**, `LEGACY_USE_AFTER_FREE_ORDERING_DETECTED`.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 1.14s**, pytest 9.2.0.
- GCC ASan was attempted for fixed and legacy binaries but its allocator CHECK fails before `main`; no ASan result is claimed. The fixed evidence is UBSan plus explicit lifetime counters and actual concurrent behavior.

## B→A RF fire — COMPLETE both sides

Resolved JSON: 6,331 bytes, SHA-256 `68fdbc650cb341848c5c2bc8325a119fa02e5f83361573f404bb8621ebecfb00`, sealed as 36 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 36/36.

- The first watcher failed closed before RF: a mechanical frame-count substitution corrupted the staged-gate and evidence paths. It was repaired, syntax/path-preflighted, and rerun; no airtime occurred on that failed attempt.
- Alpha declared receive window **B5260**, closing `2026-11-23T12:39:57Z`.
- Bravo fired inside that window: **36/36 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition.
- `frontier_solution_verdict` posts **B5262/A1666** returned `ok:true`; guard `fired_0007_B5260` prevents duplicate fire. Standby recovery passed and is active.
- Alpha capture verdict **B5271**: `DECRYPT_OK`, 36/36 frames decrypted, exact payload SHA match, receiver closure COMPLETE; Alpha also attested on devnet at slot 525435054.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525430522**, signature `3QRf3Tuy8tc2B8KTvu7YLki97YWaK7ymrYAbvGhQHdtJbwAyR9H4Kp2Atet5e87sXpHxKF4ojpfMznTSZqw843zp`.
- Record PDA `8tjBoD7sbTWmLN5MD5HWFBGJSxxrq3jiS7oGZbCY3cr` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5263/A1667** are committed. This is a digest-only attestation, not a claim of RF settlement.
