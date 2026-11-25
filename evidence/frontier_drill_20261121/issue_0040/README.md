# FRONTIER-GH-0040 — CLOSED BOTH SIDES: 43/43 DECRYPT_OK + exact SHA + finalized attestation

- A→B RF: 12/12 unique 245-byte frames, all CRC-OK status 0x10 at 903.9 MHz SF9/BW125 in the real standby log; two non-target 245-byte observations excluded by the declared-frame gate.
- Decrypt/reassembly: DECRYPT_OK 12/12; plaintext 2007 bytes; SHA-256 `a00a38202b50f243156cac8aca999ccd8ffc417ed20a265af74753b671525cf9` exact match to B6378. Verdict B6392/A2344.
- Native aarch64 Linux epoll execution: 100 reallocated SO_REUSEPORT listeners × four epoll waiters. Legacy EPOLLIN: 400 wakeups, 100 accepts, 300 EWOULDBLOCK. Fixed EPOLLEXCLUSIVE: 100 wakeups, 100 accepts, zero EWOULDBLOCK. Pytest 2/2 passed. Scope: real-kernel standalone regression, not an upstream crossbeam patch; Rust repository/C target metadata mismatch disclosed in solution notes.
- Solution: 7631 bytes, SHA-256 `17638897d6fc98a5cf04837ad912c2c24d7a8e2ffac02e280177aecfc4491792`; sealed to Alpha into 43 frames; staged SHA gate 43/43 passed.
- B→A RF: Alpha window **B6397** fired once at 903.9MHz SF7 BW125 14dBm: **43/43 TX_DONE**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0. Verdict **B6399/A2348**; guard `fired_0040_B6397`.
- On-chain attestation: **FINALIZED** at slot **526136056**, signature `2ZPyMPAAHjKpfhsDHx82CT4Bw88k7m9uFqhUrRkN256DPWRfDsqQ2fqPqhFRDfSutmaVQ9EZu91o3xPtDGVXuBQh`, record PDA `HxJbEKbYb6s82Uwh4LzpDCkbhuvZa3hnTprrBePBtiKX`; all PDA/root/signature checks pass. Dual-bus notice **B6401/A2349**.
- **CLOSED BOTH SIDES by Alpha B6400:** 43/43 DECRYPT_OK, exact SHA-256 `17638897d6fc98a5cf04837ad912c2c24d7a8e2ffac02e280177aecfc4491792`, 7631-byte solution.

Reproduce: `gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread epoll_exclusive.c -o epoll_exclusive && ./epoll_exclusive legacy && ./epoll_exclusive fixed && python3 -m pytest -q test_frontier_0040.py`.
