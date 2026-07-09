# ZK-LoRaWAN Documentation Wording & Legal Notice Realignment Walkthrough

This document records the updates implemented to bring `WHITEPAPER.md` and the compiled PDF generator (`compile_pdf.py`) into full, identical alignment with the actual repository implementations.

---

## 🔐 Implemented Realignment Updates

### 1. License & Legal Notice Correction
- **Updates**:
  - Updated the repository [LICENSE](LICENSE) file to declare the code under a **Proprietary License pending grant evaluation** by the Solana Foundation, stating that it will be re-licensed under the **Apache License, Version 2.0** upon grant approval.
  - Modified the package license definition in [programs/zk_lorawan/Cargo.toml](programs/zk_lorawan/Cargo.toml) and [groth16/Cargo.toml](groth16/Cargo.toml) to `"Proprietary"`.
  - Re-aligned the legal notices in `WHITEPAPER.md` and `compile_pdf.py` to match the Apache-2.0 target license rather than MIT.

### 2. Actual Circuit Description Realignment
- **Updates**:
  - Replaced descriptions of secp256k1, HASH160, Poseidon, and BabyJubjub/Circom with the actual implementation: **arkworks BN254 utilizing a MiMC-7 hashing circuit** (matching `groth16/src/circuit.rs`).
  - Added the correct Rust structure and constraint outline directly inside both documentation sources.

### 3. Roadmapped vs. Implemented Feature Segregation
- **Updates**:
  - Categorized ECIES, real TrustZone-M hardware enclaves, HMAC/RF-PoW, Time-of-Flight (ToF) checks, and ZK-Proof-of-Delivery (ZK-PoD) as **proposed future roadmap items** rather than active production implementations.

### 4. Batch Transaction Mode Clarification
- **Updates**:
  - Clarified that the current batch routing lifecycle uses a sequence of $N+2$ decoupled transactions (`initializeBatch` -> $N$ individual `addChirp` updates -> `submitBatch` settlement) to stay under Solana transaction limits. Single-transaction batch rollups/proof aggregation are designated as roadmap items.

### 5. Proof Compression Qualifications
- **Updates**:
  - Added a note qualifying the 189-byte/255-byte unfragmented LoRa packet claim. Real high-entropy proofs contain higher noise levels and require up to 512 bytes for uncompressed coordinates. Unfragmented 255-byte transmissions are possible only with highly constrained proof parameters, whereas general high-entropy proofs require packet fragmentation/segmentation.

### 6. PDF Curve Reference Cleanup
- **Updates**:
  - Fixed the stale BLS12-381/Pasta curve references at line 807 in `compile_pdf.py` to match the BN254 wording in `WHITEPAPER.md`.

### 7. ZK-Circuit Constraint Security Audit & Soundness Fix
- **The Vulnerability**:
  A strict PhD-level cryptographic review of [circuit.rs](file:///k:/Zk-LoRaWan/groth16/src/circuit.rs) identified a critical **under-constrained variable soundness vulnerability**. The `mimc_hash_constraints` helper function allocated new witness variables for the preimage during each hash invocation (Identity verification, Nullifier generation, and Attestation checking) without enforcing equivalence constraints. This allowed a malicious prover to supply different private key witnesses for each verification path—spoofing nullifiers or attestation values while using a valid public identity, bypassing double-spend protection and secure element checks.
- **The Fix**:
  Refactored the circuit constraints to allocate all core private witnesses exactly once (`private_key_var`, `decryption_key_var`, `coordinate_val_var`, `firmware_hash_witness_var`). Rewrote the `mimc_hash_constraints` helper to accept a `LinearCombination` representing the initial `preimage + salt` and explicitly enforce the equivalence constraint `cs.enforce_constraint(current_var.into(), Variable::One.into(), initial_lc)` at the entry point of the MiMC round loop. This guarantees that the nullifier, identity, and attestation variables are mathematically bound to the identical private key witness.
- **Verification**:
  Validated the math and execution. Running `cargo run --bin zk_lorawan_prove` and `cargo test --workspace` confirms the circuit correctly verifies valid proofs and successfully rejects tampered witnesses.

### 8. Review Hardening & CI/CD Pipeline Alignment
- **Soundness Tests**: Added [groth16/tests/circuit_soundness.rs](file:///k:/Zk-LoRaWan/groth16/tests/circuit_soundness.rs) containing 5 strict soundness tests checking variable allocation, constraint consistency, public input bindings, and witness mutations.
- **On-Chain Verify Key Points**: Updated the stale `vk_ic` points in [programs/zk_lorawan/src/lib.rs](file:///k:/Zk-LoRaWan/programs/zk_lorawan/src/lib.rs) to match the rebuilt key configurations.
- **Fixture Synchronization**: Refreshed the proof fixtures in [gateway/gateway.py](file:///k:/Zk-LoRaWan/gateway/gateway.py) and [tests/zk_lorawan.ts](file:///k:/Zk-LoRaWan/tests/zk_lorawan.ts) to align with the upgraded circuit constraints, fixing verifier mismatch.
- **Harness Hardening**: Configured [tests/verify_all_modules.py](file:///k:/Zk-LoRaWan/tests/verify_all_modules.py) and the gateway demo to fail closed if any of the 25 simulated chirps are rejected or fail verification.
- **Continuous Integration**: Added [.github/workflows/strict-verification.yml](file:///k:/Zk-LoRaWan/.github/workflows/strict-verification.yml) running Node 20.18.0 to enforce cargo tests, formatting, clippy checks, python integration, and typescript typechecks.

### 9. Linux SBF Integration & local-validator Testing
- **SBF Support**: Integrated fixes to enable the program to build and deploy inside the Solana Binary Format (SBF) VM environment on Linux.
- **Serialization & Encoding**: Corrected BN254 byte order and coordinate serialization flags to allow on-chain verifiers to match off-chain proofs.
- **Account Sizing**: Fixed batch account sizing parameters to prevent memory errors or overflow boundaries during on-chain execution.
- **CI Integration**: Added [.github/workflows/sbf-integration.yml](file:///k:/Zk-LoRaWan/.github/workflows/sbf-integration.yml) to spin up a clean Solana validator environment and execute SBF-targeted test pipelines on every push.
- **Test Results**: All 4 core transactions (Registry Initialisation, Shielded Deposit, Single Chirp, Batch Chirp) verify and settle successfully on-chain (4/4 tests passed).

### 10. Resolving Release-Blocking Audit Findings
- **Eliminated Silent Mocks**: Corrected the import block in [sdk/device_sdk.py](file:///k:/Zk-LoRaWan/sdk/device_sdk.py) to load `CuneiformCoordinate` from the proper module (`semantic_gating.range_proof`). Configured the SDK to run on real components (SemanticCodec, LLDACEncoder, XorFEC) and removed mock fallbacks completely to fail closed.
- **Strict FEC Integrity**: Updated the decoder in [fec/xor_fec.py](file:///k:/Zk-LoRaWan/fec/xor_fec.py) to raise a `ValueError` if the computed checksum doesn't match the expected checksum, protecting against silent corruption.
- **Dependency & License Alignment**: Added `pycryptodome` to [requirements-gateway.txt](file:///k:/Zk-LoRaWan/requirements-gateway.txt) to resolve execution crashes, and resolved the license badge/text contradiction in [README.md](file:///k:/Zk-LoRaWan/README.md) to match the proprietary-pending status.
- **Cryptographic Boundaries**: Documented the known parameters (deterministic setup seed, pool validation scope, gateway binding constraints, custom MiMC rounds) via warning blocks in [circuit.rs](file:///k:/Zk-LoRaWan/groth16/src/circuit.rs) and [lib.rs](file:///k:/Zk-LoRaWan/groth16/src/lib.rs).

---

## 🧪 Verification & Results

- **PDF Generation**: Compiled successfully using `python scratch/compile_pdf.py`.
- **User Downloads**: Copied the newly compiled `zk_lorawan_whitepaper.pdf` directly to `C:\Users\DannyB\Downloads\zk_lorawan_whitepaper.pdf`.
- **Git Push**: Clean pushed all changes to origin master, including the documentation realignment, the critical Groth16 circuit security fix, the CI/fixture hardening suite, and the release-blocking audit fixes.
- **Harness**: `python tests/verify_all_modules.py` runs with a clean `8/8 passed` result.
- **Device SDK Test**: `python sdk/device_sdk.py` executes successfully using real encoders and FEC (no mocks).
- **Typecheck**: `npm run typecheck` compiles TypeScript test fixtures with zero compiler warnings.
- **Rust Verification**: Cargo workspace test suite compiles and executes successfully.

### 11. Cryptographic and Shielded Pool Hardening (Active Resolution)
- **Circuit Gateway Binding**: Bound the gateway/payee public key directly as a public input (`gateway_part1` and `gateway_part2`) to the ZK-SNARK circuit to prevent front-running rewards.
- **On-Chain Merkle Membership Checks**: Integrated Merkle proof validation in the Solana Anchor program (`verify_single`, `verify_single_proof`, and `add_chirp`) against the shielded pool's current root. This ensures that the caller proofs are funded in the Merkle tree before any on-chain action or reward distribution occurs, preventing pool draining.
- **Upgrade to 220 MiMC Rounds**: Upgraded the MiMC rounds count to `220` (from `10`) across the circuit, prover CLI, and FFI verifier for standard cryptographic soundness on the BN254 curve.
- **Dynamic Integration Tests**: Refactored the TypeScript test suite (`tests/zk_lorawan.ts`) and Python gateway (`gateway/gateway.py`) to dynamically invoke the compiled `zk_lorawan_prove` CLI tool, generating mathematically valid proofs bound to the dynamic runtime gateway address.
- **Verification**: Running `cargo test --workspace` verifies circuit soundness and Rust program unit tests, while the `verify_all_modules.py` harness confirms all python modules, range proofs, and gateway engines pass successfully (`8/8 passed`).

