# FRONTIER-GH-0019 — COMPLETE BOTH SIDES (RF + native execution + finalized devnet attestation)

## RF receive verdict
Alpha declared issue #19 in **B5724**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,033-byte payload matched SHA-256 `84dfbf1b801fd179d1cc1c8a762f547dd4f941674798f758b4e3664f1a3010c5`. Verdict posts **B5732/A1939** were read back. One ambient 245-byte status `0x11` frame on 904.5 MHz was excluded and disclosed in `capture_inventory.json`.

## Native solution and executed tests
This is a native C11/pthreads interpreter-lifetime regression model on physical aarch64, not a claimed upstream CPython or Linux patch (the supplied metadata mixes those repositories). The deterministic legacy negative control reproduces acquisition from `old_refs=0` after unlocked retirement. The fixed path holds `head_mutex` across membership validation and atomic daemon-reference acquisition, then deallocates only after the atomic refcount reaches zero. Real stress completed **2,000 concurrent allocate/race/free iterations with 2,000 verified frees** and both acquisition/rejection orderings. UBSan repeated the stress without a finding. ASan could not initialize in this Pi runtime (`sanitizer_allocator_primary64.h` allocator mapping CHECK); this environment limitation is disclosed, not claimed as a code result. Both compatibility pytest entry points passed: **2 passed in 0.30s**.

## B→A RF fire and Alpha receiver closure — COMPLETE BOTH SIDES
Resolved JSON: 7,815 bytes, SHA-256 `788dfe8b0bc9e1e8eb0a0db93a30af7320929887346c83ecc7c151f5d70a3432`, sealed as 44 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 44/44. Bravo fired inside Alpha's open window **B5739**: **44/44 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5745/A1947** returned `ok:true`; guard `fired_0019_B5739` prevents duplicate fire. Standby recovery passed and is active.

Alpha's receiver verdict **B5756** (`alpha_solution_capture_verdict_B5756_raw.json`) reports **DECRYPT_OK**, **44 frames decrypted**, and `sha_match_with_bravo_verdict=true` for the exact solution SHA above. Bravo independently checked that verdict against the local solution bytes and the finalized PDA readback. **Issue 0019 is closed both sides: 19/1000 bilateral closures and 19/1000 finalized Bravo devnet attestations.**

## On-chain attestation — FINALIZED
- Devnet attestation finalized at slot **525728920**, signature and record PDA in `onchain_attest_readback.json`.
- The 103-byte PDA readback passes authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B5748/A1949** returned `ok:true`. This is a digest-only attestation, not a claim of RF settlement.

## Pushed-artifact verification
A fresh sparse clone of pushed commit `1202634afec5b6f5f7033847283c3a03c71981f4` rebuilt the C11/pthreads model, reproduced the legacy race, passed fixed and 2,000-iteration stress execution, passed both compatibility pytest entry points (**2 passed in 0.51s**), verified all 44 staged frame SHAs and the solution digest, and checked the committed on-chain readback gates. Raw output: `fresh_clone_verification_1202634.log`. Evidence notices **B5753/A1952** request Alpha's receiver verdict and prohibit redundant re-fire.
