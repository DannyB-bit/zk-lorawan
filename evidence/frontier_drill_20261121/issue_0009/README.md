# FRONTIER-GH-0009 — tagged-pointer ABA fix; RF TX and on-chain attest complete

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #9 in **B5307**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,018-byte payload matched SHA-256 `8b72fedcd6c405c4887e4e6878518d48c7e41d4e0d72ad40f91823138a93f339`. One unrelated 904.5 MHz status `0x11` observation was excluded. `frontier_issue_verdict` posts **B5322/A1701** were read back.

## Native solution and executed tests

The metadata repo is inconsistent (`python/cpython` vs `lockless_queue.c`). This is a native lock-free stack regression model, not a claimed CPython patch. Nodes remain allocated until threads join; epoch tagging addresses ABA, not general safe memory reclamation.

- Fixed head is a 16-byte pointer + 64-bit epoch pair. Explicit AArch64 `LDAXP/STLXP` CAS compares both words and increments the epoch on every successful pop/push; recycled addresses therefore fail the original CAS and retry.
- Deterministic legacy negative control: exit **2**, `LEGACY_ABA_REPRODUCED=YES`, already-popped B resurrected as head.
- Deterministic fixed test: `TAGGED_PTR_ABA_PASS=YES`, final head C, final epoch 4, `TAGGED_LOCK_FREE=1`.
- Stress: four pthreads × 50,000 iterations, **200,000 pops / 200,000 pushes**, all **128/128 nodes exactly once**, final epoch 400,128, `STRESS_PASS=YES`.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 0.15s** on physical aarch64.
- Disassembly gate: `LDAXP` and `STLXP` present; no `__atomic_load_16` or `__atomic_compare_exchange_16` calls.
- Initial harness build failed on an `atomic_store` macro/comma error and was corrected. Default GCC 16-byte atomics called libatomic and failed the lock-free gate; those discarded results are not claimed as passes. The final passing binary uses explicit ARMv8 exclusive pairs.

## B→A RF fire — COMPLETE; Alpha capture verdict pending

Resolved JSON: 12,329 bytes, SHA-256 `5a86bfd4acbcd7f1b5d646f8b1d050155a4ccea9c1898c765d49d3a65f59ca4b`, sealed as 69 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 69/69.

- Fire initiated inside Alpha window **B5331**, nominal close `2026-11-23T15:31:59Z`: **69/69 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition.
- Timing disclosure: the 69-frame, 3-second-gap schedule extended beyond that nominal close. No second fire occurred; guard `fired_0009_B5331` prevents duplication.
- `frontier_solution_verdict` posts **B5335/A1708** returned `ok:true`. Standby recovery passed and is active.
- Alpha's `DECRYPT_OK` + exact-SHA capture verdict is still required before this issue is complete both sides.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525477519**, signature `3hYD7e1FirdtcDdbgH6eS4fsCdeJ4VfzMps9WQfae23ybXbMcsgZJEi6tZZHnRQQHeMYAXhCRqbqWPXNVYeWBcbj`.
- Record PDA `MrmfQT5D1oGx6t2rGTQZZeKE5eyT7558EfeL8k1U1dd` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5336/A1709** are committed. This is a digest-only attestation, not a claim of RF settlement.
