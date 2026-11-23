# FRONTIER-GH-0003 — COMPLETE both RF directions, native CPython lifetime fix

## RF receive verdict (Bravo, 2026-11-22)

Alpha declared issue #3 as `frontier_issue_window` **B4947**. Bravo's certified standby captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`.

- 12/12 unique target frames, 12/12 AES-256-GCM `DECRYPT_OK` under `bravo_sk`.
- Reassembled issue: 2,031 bytes, SHA-256 `edb6130d55422084de34b3005dabf71db8384d658cb7d24d6917c6c1fd024cde` — exact match.
- One additional 245-byte observation failed the target status/RF gate and was excluded.
- `frontier_issue_verdict` posts **B4954/A1533** returned `ok:true` and were read back by sequence and SHA fields.

## Native solution and executed tests

The issue metadata says `torvalds/linux`, but `Python/pylifecycle.c` belongs to CPython. The patch was therefore built and tested against real `python/cpython` v3.12.0 at `0fb18b02c8ad56299d6a2910be0bab8ad601ef24`. The actual affected implementations are `Python/pystate.c` and `Python/ceval_gil.c`, plus the tstate layout in `Include/cpython/pystate.h`.

The fix takes `head_mutex` across SaveThread's swap/atomic-pin acquisition, holds that pin through `drop_gil`, releases it with atomic decrement, detaches interpreter/thread lists under `head_mutex`, and drains outstanding pins before freeing tstates.

Executed on RakMiner-B `aarch64` with GCC 14.2.0:

```text
PASS: legacy ordering reproduced free while SaveThread pin was live
PASS: patched ordering frees only after atomic pin drains
PASS: no-pin baseline and head_mutex detach boundary
test result: ok. 2 passed; 0 failed
```

The same model test passed with UndefinedBehaviorSanitizer. Full patched CPython `make -j2` succeeded. Its real test suites passed twice:

```text
test__xxsubinterpreters passed
test_embed passed
test_threading passed
Total tests: run=339 skipped=13
Result: SUCCESS
```

An optional ASan+UBSan build failed during ASan allocator initialization before `main` on this Pi runtime; this is recorded in `sanitizer_test_output.txt` and is not represented as a sanitizer test pass. The deterministic model is not represented as an upstream CPython race integration test.

## B→A RF closure — COMPLETE

Resolved JSON: 8,255 bytes, SHA-256 `1568c511d4bb812848b0f3f0648e356579347d32eba9cdf7de2073b87e74dff5`, sealed to Alpha's published X25519 key as 46 canonical RAW-mode CHIRP245 frames. The pre-fire staged-SHA gate passed 46/46.

- Alpha declared the receive window **B5060**, closing `2026-11-23T04:09:34Z`.
- Bravo's fail-closed fire completed **46/46 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm. `frontier_solution_verdict` posts **B5062/A1551** were read back.
- Alpha's capture verdict **B5067** reports `DECRYPT_OK`, **46 frames decrypted**, and exact payload SHA match. Receiver closure is therefore complete.
- A separate autonomous hot-fire subsequently repeated the same staged 46-frame burst inside Alpha's still-open declared window and posted **B5068/A1554**; its log also records 46/46 `TX_DONE`. This second transmission is retained and disclosed, not counted as a second solution.
- No on-chain settlement is claimed.
