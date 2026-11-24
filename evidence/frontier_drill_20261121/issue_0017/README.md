# FRONTIER-GH-0017 — RF received + native solution verified; B→A reply awaiting fresh window

Alpha declared issue #17 in **B5564**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,019-byte payload matched SHA-256 `0e7805cc27fe7d9e7141a942268717acc907a4d592371eaa49128bf6684c3789`. Verdict posts **B5578/A1854** were read back.

## Native solution and executed tests

This is a native ARMv8 tagged-pointer regression model on physical aarch64, not a claimed upstream CPython patch. Legacy gated interleaving: `LEGACY_ABA_REPRODUCED=YES`, worker returns recycled A and head becomes dangling B. Fixed pointer+uint64-epoch 128-bit LDAXP/STLXP CAS: stale CAS rejected once, final head NULL, `TAGGED_EPOCH_ABA_REJECTED=YES`. Primary and five repeated 4-producer/4-consumer runs each consumed 40,000/40,000 nodes with zero duplicates and final epoch 80,000. GCC C11 `-Wall -Wextra -Werror` build and both requested pytest entry points passed: **2 passed in 0.07s**. Earlier harness failures and their corrections are disclosed in the solution notes and debug artifacts.

## B→A reply state

Resolved JSON: 12,266 bytes, SHA-256 `90aacb0cb6e5032d45881245bb70bfd6d5b14c3d1d0c0eff5f1aea58d5d52779`. First Alpha window **B5568** expired before native verification completed; **no fire occurred**. Fresh-window request follows staged-SHA sealing. RF completion, Alpha capture verdict, and on-chain attestation remain pending.
