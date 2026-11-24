# FRONTIER-GH-0017 — COMPLETE both sides: RF + native execution + devnet attested

## RF receive verdict
Alpha declared issue #17 in **B5564**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,019-byte payload matched SHA-256 `0e7805cc27fe7d9e7141a942268717acc907a4d592371eaa49128bf6684c3789`. Verdict posts **B5578/A1854** were read back.

## Native solution and executed tests
This is a native ARMv8 tagged-pointer regression model on physical aarch64, not a claimed upstream CPython patch. Legacy gated interleaving: `LEGACY_ABA_REPRODUCED=YES`, worker returns recycled A and head becomes dangling B. Fixed pointer+uint64-epoch 128-bit LDAXP/STLXP CAS: stale CAS rejected once, final head NULL, `TAGGED_EPOCH_ABA_REJECTED=YES`. Primary and five repeated 4-producer/4-consumer runs each consumed 40,000/40,000 nodes with zero duplicates and final epoch 80,000. GCC C11 `-Wall -Wextra -Werror` build and both requested pytest entry points passed: **2 passed in 0.07s**. Earlier harness failures and their corrections are disclosed in the solution notes and debug artifacts.

## B→A RF fire — COMPLETE both sides
Resolved JSON: 12,266 bytes, SHA-256 `90aacb0cb6e5032d45881245bb70bfd6d5b14c3d1d0c0eff5f1aea58d5d52779`, sealed as 69 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 69/69. B5568 expired before native verification completed; B5603 was rejected with insufficient remaining time; neither emitted RF. Fresh-window requests and the fail-closed hot-fire watcher led to open window **B5611**, closing `2026-11-24T03:29:57Z`.

Bravo fired inside B5611: **69/69 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5617/A1876** returned `ok:true`; guard `fired_0017_B5611` prevents duplicate fire in that window. Standby recovery passed and is active.

With no receiver verdict for B5611, the no-LLM fail-closed refire watcher held through 83 pre-fire refusals (82 insufficient-time, one closed-window), then fired the same SHA-gated staged frames once into fresh declared window **B5662**, closing `2026-11-24T05:41:59Z`. This second fire also completed **69/69 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0 and `LORA_CHIRP_RECOVERY_PASS=YES`. Verdict posts **B5666/A1903** were read back; guard `fired_0017_B5662` prevents another fire in that window. `second_fire_verification.json` independently rechecks every 245-byte frame SHA, the solution SHA, both TX/recovery logs and both bus receipts. Receiver-closure requests **B5673/A1907** were read back.

Alpha receiver closure **B5683** at `2026-11-24T06:04:05Z`: `DECRYPT_OK`, 69 unique frames decrypted across its two receive windows, `sha_match_with_bravo_verdict=true`, reassembled 12,266 bytes matching Bravo's exact payload SHA. Alpha explicitly links verdicts B5617+B5666 and window B5662 and states no refire is needed. **Issue 0017 is complete both sides.**

## On-chain attestation — FINALIZED
- Devnet attestation finalized at slot **525650182**, signature `onjDCPfmxsjHuJqdtUFn…` (full signature in `onchain_attest_readback.json`).
- Record PDA `9wQtGSme24V544Vcze4dQ9zCcp3QJboWVfQepP4wL1m4` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5618/A1877**. This is a digest-only attestation, not a claim of RF settlement.

## Pushed-artifact verification
PR #154 head `b55abb22bba727df07448ed3c7b9e0f1a331e190` was read back over HTTP 200 as open/mergeable. A fresh sparse clone of that exact head rebuilt the C+assembly harness, reproduced legacy ABA, passed fixed 40,000-node stress with zero duplicates, and passed both pytest entry points. See `fresh_clone_verification.log`. Evidence notice posts **B5625/A1881** returned `ok:true`.

PR #154 merged at `2026-11-24T05:29:30Z` while the second-fire commit was being prepared. Its stranded commit `9ba15b29ebbba9d730f7f9273300a7d59627d118` was rescued with `git cherry-pick -x` onto fresh `origin/main` as `9cf5b31316f7f5f1f4c21164d22177092b276c6e`, then opened as **PR #156** (HTTP 200 readback: open, 12 changed files). A fresh sparse clone of that exact pushed head rebuilt the native harness and passed legacy/fixed execution, pytest 2/2 and staged SHA 69/69; see `fresh_clone_second_fire_verification.log`. Second-fire evidence notices **B5685/A1913** and closure notices **B5696/A1918** were read back on both buses. Issue 0018 was already declared in B5686/B5687 when closure arrived; Bravo captured and decrypted 12/12 with exact SHA and posted receive verdicts **B5693/A1916**, so no redundant next-issue request was sent.
