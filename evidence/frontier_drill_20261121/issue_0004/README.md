# FRONTIER-GH-0004 — native Linux epoll fix; RF TX and on-chain attest complete

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #4 as `frontier_issue_window` **B5069**. Bravo's certified standby captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`.

- 12/12 unique target frames, 12/12 AES-256-GCM `DECRYPT_OK` under `bravo_sk`.
- Reassembled issue: 2,005 bytes, SHA-256 `895463a2c022f09208d5e97964d456aa7ae9b683e77bd4238ba1730e4162007c` — exact match.
- `frontier_issue_verdict` posts **B5088/A1564** returned `ok:true` and were read back by sequence and SHA fields.

## Native solution and executed tests

The metadata names `crossbeam-rs/crossbeam`, but that Rust repository has no `net/socket/epoll_server.c`; this is a Linux C server issue. The patch adds a portable epoll registration helper and a C11 multi-producer/single-consumer accepted-fd queue. It does not claim to patch Crossbeam or the kernel.

`EPOLLEXCLUSIVE` is registered on one shared nonblocking listener in every accept worker's epoll instance. Separate `SO_REUSEPORT` sockets have separate wait queues and kernel-hash distribution; exclusive epoll wakeups do not coordinate those separate queues. The tested design therefore uses a shared listener and an atomic MPSC queue for accepted-fd distribution.

Executed on RakMiner-B `aarch64` with GCC 14.2.0:

- Strict native battery: **10/10 PASS**. Every baseline run reproduced multiple accept-worker wakeups and spurious `EWOULDBLOCK`; every exclusive run measured exactly **1 wakeup, 1 accept, 0 EWOULDBLOCK**.
- Lock-free MPSC stress: **80,000/80,000** unique ordered transfers per run, all 10 runs.
- UBSan with `halt_on_error`: **3/3 PASS**, no diagnostics.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 1.23s**, pytest 9.2.0 in an isolated scratch venv.
- ASan+UBSan did not reach `main`: AddressSanitizer's primary64 allocator CHECK failed on this Pi runtime. This is retained in `solution/sanitizer_test_output.txt` and is **not** represented as an ASan pass.
- Initial harness RED runs exposed incomplete waiter synchronization and an over-strict exact-baseline-count assumption. The final test gates each worker on its live `/proc/self/task/<tid>/syscall` entry into `epoll_wait` and asserts the valid invariant: baseline >1 wakeup versus exclusive exactly 1.

## B→A RF fire — COMPLETE; Alpha capture verdict pending

Resolved JSON: 18,039 bytes, SHA-256 `04a8db57bf9ca67a13789f17087110fcb38b9a51c5e740162bb6d76ee3e7c8d1`, sealed to Alpha's published X25519 key as 101 canonical RAW-mode CHIRP245 frames. The pre-fire staged-SHA gate passed 101/101.

- Alpha declared receive window **B5161**, closing `2026-11-23T08:45:57Z`.
- Bravo's one-shot fail-closed watcher fired inside that window: **101/101 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition.
- `frontier_solution_verdict` posts **B5165/A1607** returned `ok:true`; per-window guard `fired_0004_B5161` prevents a duplicate fire.
- Standby RX was stopped for TX, recovery passed `LORA_CHIRP_RECOVERY_PASS=YES`, and standby is active again.
- Alpha's `DECRYPT_OK` + exact-SHA capture verdict is still required before this issue is complete both sides.

## On-chain attestation — FINALIZED

- Devnet `register_coordinates` attestation finalized at slot **525372041**, signature `3zv9PFNbFdovvVLEqcaGAAVu…` (full signature in `onchain_attest_readback.json`).
- Record PDA `BzXwS5cBB4U6eEF6P2Uv9eHvJhE3DpfNv7ybFdHEa6Tz` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus `frontier_onchain_attest` notices **B5166/A1608** are committed with the verbatim chain readback. This is a digest-only attestation, not a claim of RF settlement.
