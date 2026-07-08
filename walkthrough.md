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

---

## 🧪 Verification & Results

- **PDF Generation**: Compiled successfully using `python scratch/compile_pdf.py`.
- **User Downloads**: Copied the newly compiled `zk_lorawan_whitepaper.pdf` directly to `C:\Users\DannyB\Downloads\zk_lorawan_whitepaper.pdf`.
- **Git Push**: Clean pushed all changes to origin master, including the documentation realignment and the critical Groth16 circuit security fix.
- **Harness**: `python tests/verify_all_modules.py` runs with a clean `7/7 passed` result.
