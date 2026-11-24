# FRONTIER-GH-0001 — sealed A→B issue, native ABA fix, sealed B→A solution

## RF receive verdict (Bravo, 2026-11-22)

Alpha declared the combined brief+issue re-fire as `frontier_issue_window` **B4888/A1519** and fired into Bravo's certified window B4882/A1516. Alpha's fire receipt is **B4890/A1520**.

Bravo captured 41 CRC-OK observations of the 29 declared 245-byte frames at 903.9 MHz, SF9/BW125, SNR +10.5..+11.8 dB: 29 unique frame SHAs, with 12 repeat observations. Two additional 245-byte frames were excluded by the CRC/status/RF gate.

- Mission brief: 17/17 unique frames, 17/17 AES-256-GCM `DECRYPT_OK`, reassembled 2,923 bytes, SHA-256 `5e7ea0635f171ce089c27cb005253cc0bc04ba7cd8719d57dcb8d61c9f558c75` — exact match.
- Issue: 12/12 unique frames, 12/12 `DECRYPT_OK`, reassembled 2,018 bytes, SHA-256 `d0bd6720e01c5167c2ae8615d5603de0a3e1d31d332c9dd94ae91ad132be5d6f` — exact match.
- Receive verdict posts: B4900/A1523, both POSTs returned `ok:true` and were persisted in `frontier_issue_verdict_post.json`.

## Native solution and executed test

The patch replaces pointer-only CAS with an atomic 128-bit `{pointer, uint64_t epoch}` head and increments the generation on every successful push/pop. Acquire loads and acq_rel CAS success ordering preserve synchronization. The notes explicitly retain the requirement for safe memory reclamation when nodes are freed; a tag prevents ABA, not use-after-free.

Executed on this Raspberry Pi's `aarch64` silicon with GCC 14.2.0:

```text
PASS: legacy ABA reproduced; 128-bit ptr+64-bit-epoch CAS rejected stale generation; LIFO baseline passed
PASS: 2/2 direct test functions (pytest module not installed)
```

The pytest module is not installed. The same two test functions were invoked directly; no pytest run is claimed. An initial compile exposed a missing `<stddef.h>` include; it was fixed before the final passing run.

## RF solution transmission

Resolved JSON: 6,276 bytes, SHA-256 `83d25cbd59424317d3fdc183f0605c6ef67612b88673c717296c805f386bcd26`. It was sealed to Alpha's published X25519 key as 35 canonical RAW-mode CHIRP245 frames. The pre-fire staged-SHA gate passed 35/35.

Bravo fired inside Alpha's declared solution window B4893/A1521 (close 07:44:52Z): 35/35 `TX_DONE`, `CHIRP_TX_COMPLETE=YES`, TX exit 0, post-TX recovery exit 0. `frontier_solution_verdict` posts are B4902/A1524. Bravo RX standby was re-certified and re-armed after TX.

`ok:true` on B4902/A1524 is Bravo's staging+TX verdict only. Issue completion requires Alpha's receive-side `DECRYPT_OK` and exact payload-SHA confirmation. No on-chain settlement is claimed in this dossier.
