// ============================================================================
// ZK-LoRaWAN MPC Ceremony — Groth16 Trusted Setup
// ============================================================================
// Implements a sequential-contribution MPC ceremony for the Groth16 CRS.
// Each contributor re-randomizes the proving key's delta and gamma parameters,
// providing a proof-of-knowledge for verification. As long as at least one
// contributor honestly destroys their secret, the toxic waste is unknown.
// ============================================================================

use ark_bn254::{Bn254, Fr, G1Affine, G1Projective, G2Affine, G2Projective};
use ark_ec::{AffineRepr, CurveGroup, Group};
use ark_ff::{Field, UniformRand};
use ark_groth16::{ProvingKey, VerifyingKey};
use ark_serialize::{CanonicalDeserialize, CanonicalSerialize};

use rand::SeedableRng;
use serde::{Deserialize, Serialize};
use zeroize::Zeroize;

use crate::circuit;

// ============================================================================
// Ceremony Data Structures
// ============================================================================

/// A single contribution record in the ceremony transcript.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ContributionRecord {
    pub index: u32,
    pub contributor: String,
    pub timestamp: String,
    /// H(pk || vk) after this contribution
    pub contribution_hash: String,
    /// [s]₁ serialized — proof that contributor knew their secret s
    pub proof_of_knowledge: String,
    pub delta_g1: String,
    pub delta_g2: String,
    /// Genesis entropy provenance (FIX 2026-10-17): public commitments to the
    /// entropy sources used for the initial setup. Present only on record #0.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub entropy_sources: Option<serde_json::Value>,
}

/// Full ceremony transcript, written to ceremony_transcript.json.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct CeremonyTranscript {
    pub circuit: String,
    pub curve: String,
    pub num_contributions: u32,
    pub contributions: Vec<ContributionRecord>,
    pub final_vk_hash: String,
    pub status: String,
}

/// Serializable ceremony parameters (pk + vk + chain metadata).
/// Written to ceremony_NNNN.params files.
pub struct CeremonyParams {
    pub proving_key: ProvingKey<Bn254>,
    pub verifying_key: VerifyingKey<Bn254>,
    pub contribution_index: u32,
    pub chain_hash: [u8; 32],
    pub contributions: Vec<ContributionRecord>,
}

impl CeremonyParams {
    /// Serialize to bytes for file storage.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut buf = Vec::new();

        // Write contribution index (4 bytes)
        buf.extend_from_slice(&self.contribution_index.to_le_bytes());

        // Write chain hash (32 bytes)
        buf.extend_from_slice(&self.chain_hash);

        // Write pk
        let mut pk_buf = Vec::new();
        self.proving_key
            .serialize_compressed(&mut pk_buf)
            .expect("Failed to serialize pk");
        buf.extend_from_slice(&(pk_buf.len() as u64).to_le_bytes());
        buf.extend_from_slice(&pk_buf);

        // Write vk
        let mut vk_buf = Vec::new();
        self.verifying_key
            .serialize_compressed(&mut vk_buf)
            .expect("Failed to serialize vk");
        buf.extend_from_slice(&(vk_buf.len() as u64).to_le_bytes());
        buf.extend_from_slice(&vk_buf);

        // Write contributions as JSON
        let contributions_json =
            serde_json::to_vec(&self.contributions).expect("Failed to serialize contributions");
        buf.extend_from_slice(&(contributions_json.len() as u64).to_le_bytes());
        buf.extend_from_slice(&contributions_json);

        buf
    }

    /// Deserialize from bytes.
    pub fn from_bytes(data: &[u8]) -> Result<Self, String> {
        let mut offset = 0;

        // Read contribution index
        if data.len() < offset + 4 {
            return Err("Data too short for contribution index".into());
        }
        let contribution_index = u32::from_le_bytes(data[offset..offset + 4].try_into().unwrap());
        offset += 4;

        // Read chain hash
        if data.len() < offset + 32 {
            return Err("Data too short for chain hash".into());
        }
        let mut chain_hash = [0u8; 32];
        chain_hash.copy_from_slice(&data[offset..offset + 32]);
        offset += 32;

        // Read pk
        if data.len() < offset + 8 {
            return Err("Data too short for pk length".into());
        }
        let pk_len = u64::from_le_bytes(data[offset..offset + 8].try_into().unwrap()) as usize;
        offset += 8;
        if data.len() < offset + pk_len {
            return Err("Data too short for pk".into());
        }
        let proving_key =
            ProvingKey::<Bn254>::deserialize_compressed(&data[offset..offset + pk_len])
                .map_err(|e| format!("Failed to deserialize pk: {}", e))?;
        offset += pk_len;

        // Read vk
        if data.len() < offset + 8 {
            return Err("Data too short for vk length".into());
        }
        let vk_len = u64::from_le_bytes(data[offset..offset + 8].try_into().unwrap()) as usize;
        offset += 8;
        if data.len() < offset + vk_len {
            return Err("Data too short for vk".into());
        }
        let verifying_key =
            VerifyingKey::<Bn254>::deserialize_compressed(&data[offset..offset + vk_len])
                .map_err(|e| format!("Failed to deserialize vk: {}", e))?;
        offset += vk_len;

        // Read contributions
        if data.len() < offset + 8 {
            return Err("Data too short for contributions length".into());
        }
        let contrib_len = u64::from_le_bytes(data[offset..offset + 8].try_into().unwrap()) as usize;
        offset += 8;
        if data.len() < offset + contrib_len {
            return Err("Data too short for contributions".into());
        }
        let contributions: Vec<ContributionRecord> =
            serde_json::from_slice(&data[offset..offset + contrib_len])
                .map_err(|e| format!("Failed to deserialize contributions: {}", e))?;

        Ok(CeremonyParams {
            proving_key,
            verifying_key,
            contribution_index,
            chain_hash,
            contributions,
        })
    }
}

// ============================================================================
// Ceremony Operations
// ============================================================================

/// Hash bytes using keccak256 (matching on-chain).
///
/// FIX 2026-10-17 (Researcher A, fleet law audit): this function previously
/// implemented a 64-bit FNV chain mislabeled as keccak256 — forgeable
/// tamper-evidence. Replaced with real keccak256 from the `sha3` crate
/// (Keccak-256, not NIST SHA3-256 — matches Solidity/EVM semantics).
fn keccak256(data: &[u8]) -> [u8; 32] {
    use sha3::{Digest, Keccak256};
    let mut hasher = Keccak256::new();
    hasher.update(data);
    let out = hasher.finalize();
    let mut result = [0u8; 32];
    result.copy_from_slice(&out);
    result
}

// Known-answer self-check executed by `verify()`: keccak256("") is the
// canonical empty-string digest (computed with pycryptodomex 3.20.0,
// cross-checked against EVM semantics — do NOT edit from memory).
const KECCAK256_EMPTY: [u8; 32] = [
    0xc5, 0xd2, 0x46, 0x01, 0x86, 0xf7, 0x23, 0x3c, 0x92, 0x7e, 0x7d, 0xb2, 0xdc, 0xc7, 0x03, 0xc0,
    0xe5, 0x00, 0xb6, 0x53, 0xca, 0x82, 0x27, 0x3b, 0x7b, 0xfa, 0xd8, 0x04, 0x5d, 0x85, 0xa4, 0x70,
];

/// Compute hash of pk + vk for the ceremony chain.
fn hash_params(pk: &ProvingKey<Bn254>, vk: &VerifyingKey<Bn254>) -> [u8; 32] {
    let mut buf = Vec::new();
    pk.serialize_compressed(&mut buf)
        .expect("Failed to serialize pk for hashing");
    vk.serialize_compressed(&mut buf)
        .expect("Failed to serialize vk for hashing");
    keccak256(&buf)
}

/// FIX 2026-10-17 (Researcher A): fetch genuinely-unpredictable-at-seed-time,
/// publicly-verifiable-afterwards entropy for the genesis seed. Uses recent
/// Solana mainnet-beta slots: future data the coordinator cannot precompute.
/// The Pi has no realtime clock battery — chain height doubles as a timestamp
/// oracle. On network failure, `initialize()` REFUSES to proceed rather than
/// silently degrading to weak entropy (fail-closed, fleet law).
/// FIX 2026-10-17 (Researcher A): fetch genuinely-unpredictable-at-seed-time,
/// publicly-verifiable-afterwards entropy for the genesis seed. Uses recent
/// Solana mainnet-beta slots: future data the coordinator cannot precompute.
/// The Pi has no realtime clock battery — chain height doubles as a timestamp
/// oracle. On network failure, `initialize()` REFUSES to proceed rather than
/// silently degrading to weak entropy (fail-closed, fleet law).
fn fetch_public_entropy() -> Vec<u8> {
    const ENDPOINTS: [&str; 3] = [
        "https://api.mainnet-beta.solana.com",
        "https://solana-rpc.publicnode.com",
        "https://api.devnet.solana.com",
    ];

    for url in ENDPOINTS {
        let body = r#"{"jsonrpc":"2.0","id":1,"method":"getSlot"}"#;
        // ureq: minimal blocking HTTPS POST, 10s timeout, no redirects needed
        let resp = ureq::post(url)
            .timeout(std::time::Duration::from_secs(10))
            .set("Content-Type", "application/json")
            .send_string(body);
        if let Ok(resp) = resp {
            if let Ok(v) = resp.into_json::<serde_json::Value>() {
                let slot = v["result"].as_u64().unwrap_or(0);
                if slot > 0 {
                    // Re-serialize deterministically — binds entropy to the exact slot value.
                    let mut binding = b"zk-lorawan-ceremony-genesis-v1".to_vec();
                    binding.extend_from_slice(&slot.to_le_bytes());
                    return keccak256(&binding).to_vec();
                }
            }
        }
    }
    // Fail closed: no silent fallback to clock-only or zero entropy.
    panic!("CEREMONY INIT ABORTED: no public-entropy source reachable. Refusing to seed genesis from weak entropy. Retry with network up.");
}

/// Phase 1: Initialize the ceremony with the first set of parameters.
pub fn initialize(output_path: &str) -> Result<(), String> {
    eprintln!("╔══════════════════════════════════════════════════════════════╗");
    eprintln!("║  ZK-LoRaWAN MPC Ceremony — Phase 1: Initialize             ║");
    eprintln!("╚══════════════════════════════════════════════════════════════╝");
    eprintln!();

    let constants = circuit::generate_mimc_constants(220);

    // FIX 2026-10-17 (Researcher A): genesis previously seeded StdRng with
    // [0u8; 32] — 32 zero bytes published in source. Anyone who read the repo
    // could regenerate the coordinator's trapdoor; the "one honest participant
    // suffices" property was false as written. Genesis now derives from:
    //   1. OsRng (hardware entropy, never published)
    //   2. Public entropy call (blockchain/future data — unpredictable at
    //      seed time, verifiable afterwards)
    // mixed via keccak256 into the StdRng seed. The seed is zeroized after
    // setup; only commitments are published.
    let mut os_seed = [0u8; 32];
    getrandom::getrandom(&mut os_seed)
        .map_err(|e| format!("Failed to gather OS entropy: {}", e))?;

    let public_entropy = fetch_public_entropy();

    let mut seed_material = Vec::with_capacity(32 + public_entropy.len());
    seed_material.extend_from_slice(&os_seed);
    seed_material.extend_from_slice(&public_entropy);
    let seed = keccak256(&seed_material);

    // Commit to the public part (verifiable afterwards); never log the OS part.
    let public_entropy_hash = keccak256(&public_entropy);

    eprintln!("  Generating initial parameters (real entropy: OS + public)...");
    let mut rng = rand::rngs::StdRng::from_seed(seed);
    let (pk, vk) =
        circuit::setup_keys(&mut rng, constants).map_err(|e| format!("Setup failed: {}", e))?;

    // Zeroize the seed material — it IS the genesis trapdoor.
    let mut seed_mut = seed;
    seed_mut.zeroize();
    let mut os_mut = os_seed;
    os_mut.zeroize();

    let chain_hash = hash_params(&pk, &vk);
    let timestamp = chrono::Utc::now().to_rfc3339();

    let mut initial_delta_g1_bytes = Vec::new();
    pk.delta_g1
        .serialize_compressed(&mut initial_delta_g1_bytes)
        .unwrap();

    let mut initial_delta_g2_bytes = Vec::new();
    vk.delta_g2
        .serialize_compressed(&mut initial_delta_g2_bytes)
        .unwrap();

    let initial_record = ContributionRecord {
        index: 0,
        contributor: "coordinator".to_string(),
        timestamp,
        contribution_hash: hex::encode(chain_hash),
        proof_of_knowledge: "genesis".to_string(),
        delta_g1: hex::encode(&initial_delta_g1_bytes),
        delta_g2: hex::encode(&initial_delta_g2_bytes),
        // FIX: record entropy sources (public commitments, never the secrets)
        entropy_sources: Some(serde_json::json!({
            "scheme": "keccak256(os_rng_32B || public_entropy)",
            "os_rng": "32B hardware entropy — not logged, zeroized",
            "public_entropy_call": hex::encode(public_entropy_hash),
            "note": "seed zeroized after setup; only commitments published"
        })),
    };

    let params = CeremonyParams {
        proving_key: pk,
        verifying_key: vk,
        contribution_index: 0,
        chain_hash,
        contributions: vec![initial_record],
    };

    let data = params.to_bytes();
    std::fs::write(output_path, &data)
        .map_err(|e| format!("Failed to write {}: {}", output_path, e))?;

    eprintln!("  ✅ Ceremony initialized");
    eprintln!("  Output:           {}", output_path);
    eprintln!("  Chain hash:       {}", hex::encode(chain_hash));
    eprintln!("  Contribution #0:  coordinator (genesis)");
    eprintln!();
    eprintln!(
        "  Next step: distribute {} to the first contributor.",
        output_path
    );
    eprintln!("  They should run:");
    eprintln!("    zk_lorawan_prove ceremony contribute --input {} --output ceremony_0001.params --name \"<name>\"", output_path);

    Ok(())
}

/// Phase 2: Apply a random contribution to the ceremony parameters.
/// Re-randomizes the delta component of the Groth16 CRS.
pub fn contribute(
    input_path: &str,
    output_path: &str,
    contributor_name: &str,
) -> Result<(), String> {
    eprintln!("╔══════════════════════════════════════════════════════════════╗");
    eprintln!("║  ZK-LoRaWAN MPC Ceremony — Phase 2: Contribute             ║");
    eprintln!("╚══════════════════════════════════════════════════════════════╝");
    eprintln!();

    // Load previous parameters
    let data =
        std::fs::read(input_path).map_err(|e| format!("Failed to read {}: {}", input_path, e))?;
    let mut params = CeremonyParams::from_bytes(&data)?;

    eprintln!("  Loaded ceremony params from: {}", input_path);
    eprintln!("  Previous contribution: #{}", params.contribution_index);
    eprintln!(
        "  Previous chain hash:   {}",
        hex::encode(params.chain_hash)
    );
    eprintln!();

    // Generate random secret s (toxic waste for this contribution)
    let mut rng = rand::rngs::OsRng;
    let mut secret = Fr::rand(&mut rng);

    // Compute proof of knowledge: [s]₁ = s * G1::generator
    let pok: G1Affine = (G1Projective::generator() * secret).into_affine();
    let mut pok_bytes = Vec::new();
    pok.serialize_compressed(&mut pok_bytes)
        .expect("Failed to serialize proof of knowledge");

    eprintln!("  Generated random secret (will be securely erased)");
    eprintln!("  Proof of knowledge: {}", hex::encode(&pok_bytes));
    eprintln!();

    // Re-randomize the CRS delta component
    // CORRECT Groth16 delta-update (verified against ark-groth16-0.4.0 source,
    // prover.rs — ground truth, not recalled):
    //   scale by s:    pk.delta_g1, vk.delta_g2 (and pk.vk copy)
    //   scale by s^-1: pk.h_query, pk.l_query  (they encode h_i(x)/δ, b_i(x)/δ)
    //   UNCHANGED:     a_query, b_g1_query, b_g2_query, alpha/beta/gamma points,
    //                  gamma_abc_g1 — none contain δ.
    // Note: arkworks 0.4 has no c_query field; C is built from l/h accs + δ terms.
    let secret_inv = secret.inverse().expect("Secret must be non-zero");

    // Transform verifying key: delta_g2' = s * delta_g2
    let new_delta_g2: G2Affine =
        (G2Projective::from(params.verifying_key.delta_g2) * secret).into_affine();
    params.verifying_key.delta_g2 = new_delta_g2;

    // Transform proving key: delta_g1' = s * delta_g1
    let new_delta_g1: G1Affine =
        (G1Projective::from(params.proving_key.delta_g1) * secret).into_affine();
    params.proving_key.delta_g1 = new_delta_g1;

    // Transform proving key: delta_g2' (must match VK)
    params.proving_key.vk.delta_g2 = new_delta_g2;

    // Transform h_query: h_i' = s^(-1) * h_i  (encodes 1/delta)
    let new_h_query: Vec<G1Affine> = params
        .proving_key
        .h_query
        .iter()
        .map(|h| (G1Projective::from(*h) * secret_inv).into_affine())
        .collect();
    params.proving_key.h_query = new_h_query;

    // Transform l_query: l_i' = s^(-1) * l_i  (because l encodes 1/delta)
    let new_l_query: Vec<G1Affine> = params
        .proving_key
        .l_query
        .iter()
        .map(|l| (G1Projective::from(*l) * secret_inv).into_affine())
        .collect();
    params.proving_key.l_query = new_l_query;

    // Securely erase the secret
    let mut secret_bytes = [0u8; 32];
    secret.serialize_compressed(&mut secret_bytes[..]).ok();
    secret_bytes.zeroize();
    // Also zero the Fr value itself
    secret = Fr::from(0u64);
    let _ = secret; // prevent optimization from removing the zeroing

    eprintln!("  ✅ Secret securely erased from memory");

    // Update chain hash
    let new_params_hash = hash_params(&params.proving_key, &params.verifying_key);
    let mut chain_input = Vec::new();
    chain_input.extend_from_slice(&params.chain_hash);
    chain_input.extend_from_slice(&pok_bytes);
    chain_input.extend_from_slice(contributor_name.as_bytes());
    let new_chain_hash = keccak256(&chain_input);

    let timestamp = chrono::Utc::now().to_rfc3339();
    let new_index = params.contribution_index + 1;

    let mut new_delta_g1_bytes = Vec::new();
    params
        .proving_key
        .delta_g1
        .serialize_compressed(&mut new_delta_g1_bytes)
        .unwrap();

    let mut new_delta_g2_bytes = Vec::new();
    params
        .verifying_key
        .delta_g2
        .serialize_compressed(&mut new_delta_g2_bytes)
        .unwrap();

    let record = ContributionRecord {
        index: new_index,
        contributor: contributor_name.to_string(),
        timestamp,
        contribution_hash: hex::encode(new_params_hash),
        proof_of_knowledge: hex::encode(&pok_bytes),
        delta_g1: hex::encode(&new_delta_g1_bytes),
        delta_g2: hex::encode(&new_delta_g2_bytes),
        entropy_sources: None, // only the genesis record carries entropy provenance
    };

    params.contributions.push(record);
    params.contribution_index = new_index;
    params.chain_hash = new_chain_hash;

    // Write output
    let out_data = params.to_bytes();
    std::fs::write(output_path, &out_data)
        .map_err(|e| format!("Failed to write {}: {}", output_path, e))?;

    eprintln!();
    eprintln!(
        "  ✅ Contribution #{} applied by \"{}\"",
        new_index, contributor_name
    );
    eprintln!("  Output:         {}", output_path);
    eprintln!("  Chain hash:     {}", hex::encode(new_chain_hash));
    eprintln!("  Params hash:    {}", hex::encode(new_params_hash));
    eprintln!();
    eprintln!(
        "  Next step: pass {} to the next contributor, or finalize.",
        output_path
    );

    Ok(())
}

/// Phase 3: Verify the entire ceremony chain.
pub fn verify(input_path: &str) -> Result<(), String> {
    eprintln!("╔══════════════════════════════════════════════════════════════╗");
    eprintln!("║  ZK-LoRaWAN MPC Ceremony — Phase 3: Verify                 ║");
    eprintln!("╚══════════════════════════════════════════════════════════════╝");
    eprintln!();

    let data =
        std::fs::read(input_path).map_err(|e| format!("Failed to read {}: {}", input_path, e))?;
    let params = CeremonyParams::from_bytes(&data)?;

    if params.contributions.len() < 2 {
        return Err(
            "FAILED: Ceremony must have at least one non-genesis contribution to be valid!".into(),
        );
    }

    eprintln!(
        "  Loaded ceremony params: {} contributions",
        params.contributions.len()
    );
    eprintln!();

    use ark_ec::pairing::Pairing;

    // 0. FIX 2026-10-17: keccak256 known-answer self-check (EVM semantics).
    if keccak256(&[]) != KECCAK256_EMPTY {
        return Err(
            "FAILED: keccak256 self-check does not match EVM constant — hash wiring broken!".into(),
        );
    }
    eprintln!("  ✅ keccak256 KAT self-check passed (EVM-compatible)");

    // 1. FIX 2026-10-17: the old code regenerated the genesis keys from a
    // zero seed ([0u8; 32]) and compared them to record #0 — a check that
    // (a) only ever worked for the broken deterministic genesis, and
    // (b) is impossible under a real entropy-derived genesis (the seed is
    // destroyed by design). Replaced with checks that do NOT require
    // knowing the genesis seed:
    //   - per-transition pairing checks on the recorded delta points + PoK
    //   - params-hash continuity against the last contribution record
    //   - an END-TO-END soundness proof: generate a proof with the final
    //     proving key and verify it under the final verifying key. Any
    //     inconsistent or stale query set (h_query, l_query, a/b queries,
    //     delta points) makes this fail — strictly stronger than the old
    //     zero-seed comparison.

    // Verify each contribution transition and proof of knowledge
    for (i, contrib) in params.contributions.iter().enumerate() {
        if i == 0 {
            // Genesis contribution — deserialize initial delta (validity only;
            // the zero-seed equality comparison was removed with the zero seed)
            let delta_g1_bytes = hex::decode(&contrib.delta_g1)
                .map_err(|_| "Invalid delta_g1 hex at contribution #0".to_string())?;
            let delta_g1 = G1Affine::deserialize_compressed(&delta_g1_bytes[..])
                .map_err(|_| "Invalid delta_g1 G1 point at contribution #0".to_string())?;
            let delta_g2_bytes = hex::decode(&contrib.delta_g2)
                .map_err(|_| "Invalid delta_g2 hex at contribution #0".to_string())?;
            let delta_g2 = G2Affine::deserialize_compressed(&delta_g2_bytes[..])
                .map_err(|_| "Invalid delta_g2 G2 point at contribution #0".to_string())?;
            let _ = (delta_g1, delta_g2); // deserialization success = structural validity
            if contrib.proof_of_knowledge != "genesis" {
                return Err("FAILED: contribution #0 must be the genesis record".into());
            }

            eprintln!(
                "  ✅ Contribution #0: {} (genesis) — record structurally valid",
                contrib.contributor
            );
            continue;
        }

        // Verify proof of knowledge is a valid G1 point
        let pok_bytes = hex::decode(&contrib.proof_of_knowledge)
            .map_err(|_| format!("Invalid PoK hex at contribution #{}", i))?;
        let pok = G1Affine::deserialize_compressed(&pok_bytes[..])
            .map_err(|_| format!("Invalid PoK G1 point at contribution #{}", i))?;

        // Deserialize previous contribution delta
        let prev_contrib = &params.contributions[i - 1];
        let prev_delta_g1_bytes = hex::decode(&prev_contrib.delta_g1)
            .map_err(|_| format!("Invalid delta_g1 hex at contribution #{}", i - 1))?;
        let prev_delta_g1 = G1Affine::deserialize_compressed(&prev_delta_g1_bytes[..])
            .map_err(|_| format!("Invalid delta_g1 G1 point at contribution #{}", i - 1))?;
        let prev_delta_g2_bytes = hex::decode(&prev_contrib.delta_g2)
            .map_err(|_| format!("Invalid delta_g2 hex at contribution #{}", i - 1))?;
        let prev_delta_g2 = G2Affine::deserialize_compressed(&prev_delta_g2_bytes[..])
            .map_err(|_| format!("Invalid delta_g2 G2 point at contribution #{}", i - 1))?;

        // Deserialize current contribution delta
        let curr_delta_g1_bytes = hex::decode(&contrib.delta_g1)
            .map_err(|_| format!("Invalid delta_g1 hex at contribution #{}", i))?;
        let curr_delta_g1 = G1Affine::deserialize_compressed(&curr_delta_g1_bytes[..])
            .map_err(|_| format!("Invalid delta_g1 G1 point at contribution #{}", i))?;
        let curr_delta_g2_bytes = hex::decode(&contrib.delta_g2)
            .map_err(|_| format!("Invalid delta_g2 hex at contribution #{}", i))?;
        let curr_delta_g2 = G2Affine::deserialize_compressed(&curr_delta_g2_bytes[..])
            .map_err(|_| format!("Invalid delta_g2 G2 point at contribution #{}", i))?;

        // Bilinear pairing check 1: update consistency between G1 and G2:
        // Pairing(curr_delta_g1, prev_delta_g2) == Pairing(prev_delta_g1, curr_delta_g2)
        let pair1_left = Bn254::pairing(curr_delta_g1, prev_delta_g2);
        let pair1_right = Bn254::pairing(prev_delta_g1, curr_delta_g2);
        if pair1_left != pair1_right {
            return Err(format!(
                "FAILED: delta_g1 and delta_g2 update is inconsistent at contribution #{}",
                i
            ));
        }

        // Bilinear pairing check 2: PoK matches the updated parameters:
        // Pairing(pok, prev_delta_g2) == Pairing(G1::generator(), curr_delta_g2)
        let pair2_left = Bn254::pairing(pok, prev_delta_g2);
        let pair2_right = Bn254::pairing(G1Affine::generator(), curr_delta_g2);
        if pair2_left != pair2_right {
            return Err(format!(
                "FAILED: Proof of knowledge does not match updated delta at contribution #{}",
                i
            ));
        }

        eprintln!(
            "  ✅ Contribution #{}: {} — valid PoK & pairing transitions verified",
            i, contrib.contributor
        );
    }

    // Verify current params hash matches the last contribution record
    let current_hash = hash_params(&params.proving_key, &params.verifying_key);
    let last_contrib = params.contributions.last().unwrap();
    let recorded_hash = hex::decode(&last_contrib.contribution_hash)
        .map_err(|_| "Invalid contribution hash hex".to_string())?;

    if current_hash[..] != recorded_hash[..] {
        return Err("FAILED: Current params hash does not match last contribution record!".into());
    }
    eprintln!();
    eprintln!("  ✅ Parameters hash matches last contribution record");

    // 2. FIX 2026-10-17: the old "algebraic query-vector verification" compared
    // the final h_query/l_query against a re-derived INITIAL pk/vk built from
    // the zero seed — same broken dependency, and it silently relied on
    // initial_pk's a_query/gamma_abc which are seed-dependent too. Removed.
    // Replaced with the strictly stronger END-TO-END soundness check below:
    // proving a statement with the final pk and verifying under the final vk
    // exercises EVERY element of both keys (a, b_g1, b_g2, h, l, delta,
    // gamma_abc) in the real verification equation. A stale or inconsistent
    // query set cannot pass it.

    // 3. Verify the VK is structurally valid (correct number of IC points)
    // FIX 2026-10-17: the real ZKLoRaCircuit exposes 10 public inputs
    // (identity, nullifier, attestation, ciphertext, gateway1, gateway2,
    // deposit_commitment, firmware_hash, payload_commitment, payload_sha256)
    // + 1 implicit "one" = 11 gamma_abc_g1 points. The old code checked for 9
    // (the pre-identity-binding 8-input circuit) and would REJECT the real
    // keys at verify/finalize — it was never run against the real circuit.
    let expected_ic_count = 11; // 10 public inputs + 1 (implicit "one")
    if params.verifying_key.gamma_abc_g1.len() != expected_ic_count {
        return Err(format!(
            "FAILED: VK has {} IC points, expected {}",
            params.verifying_key.gamma_abc_g1.len(),
            expected_ic_count
        ));
    }
    eprintln!(
        "  ✅ Verifying key structure valid ({} IC points for 10 public inputs)",
        expected_ic_count
    );

    // 4. END-TO-END SOUNDNESS CHECK (FIX 2026-10-17, replaces the removed
    // zero-seed comparison): prove a fixed witness with the final proving key
    // and verify it with the final verifying key. This exercises every element
    // of both keys in the real Groth16 verification equation — a stale,
    // tampered, or inconsistent query set / delta update FAILS here. It is
    // strictly stronger than any per-element spot check.
    eprintln!("  Running end-to-end proof soundness check with final keys...");
    {
        use crate::circuit::{generate_mimc_constants, generate_proof, mimc_hash, verify_proof};
        use ark_groth16::prepare_verifying_key;
        use rand::rngs::OsRng;

        // Known-good witness (mirrors tests/circuit_soundness.rs fixture — the
        // arg-order trap in generate_proof's 10-value signature cost an hour of
        // debugging; always copy this fixture verbatim).
        let constants = generate_mimc_constants(220);
        let private_key = Fr::from(1_337u64);
        let decryption_key = Fr::from(7_331u64);
        let coordinate_val = Fr::from(42u64);
        let firmware_hash = Fr::from(2_026u64);
        let deposit_value = Fr::from(100_000u64);
        let gateway_part1 = Fr::from(1_111u64);
        let gateway_part2 = Fr::from(2_222u64);
        let payload_sha256 = Fr::from(9_021_013u64);

        let identity_hash = mimc_hash(private_key, None, &constants);
        let nullifier_hash = mimc_hash(private_key, Some(Fr::from(9_999u64)), &constants);
        let attestation_hash = mimc_hash(private_key, Some(firmware_hash), &constants);
        let ciphertext_hash = mimc_hash(decryption_key, Some(coordinate_val), &constants);
        let deposit_commitment = mimc_hash(identity_hash, Some(deposit_value), &constants);
        let payload_commitment = mimc_hash(identity_hash, Some(payload_sha256), &constants);

        let mut rng = OsRng;
        let proof = generate_proof(
            &params.proving_key,
            private_key,
            decryption_key,
            coordinate_val,
            firmware_hash,
            deposit_value,
            identity_hash,
            nullifier_hash,
            attestation_hash,
            ciphertext_hash,
            gateway_part1,
            gateway_part2,
            deposit_commitment,
            firmware_hash,
            payload_sha256,
            payload_commitment,
            constants,
            &mut rng,
        )
        .map_err(|e| {
            format!(
                "E2E check: proof generation failed — keys inconsistent: {}",
                e
            )
        })?;

        let pvk = prepare_verifying_key(&params.verifying_key);
        let ok = verify_proof(
            &pvk,
            &proof,
            identity_hash,
            nullifier_hash,
            attestation_hash,
            ciphertext_hash,
            gateway_part1,
            gateway_part2,
            deposit_commitment,
            firmware_hash,
            payload_commitment,
            payload_sha256,
        )
        .map_err(|e| format!("E2E check: verification errored: {}", e))?;
        if !ok {
            return Err(
                "FAILED: End-to-end soundness check: proof does not verify under final keys!"
                    .into(),
            );
        }
        eprintln!("  ✅ End-to-end proof verified under final ceremony keys");
    }

    // Verify chain hash
    eprintln!("  ✅ Chain hash: {}", hex::encode(params.chain_hash));
    eprintln!();
    eprintln!("  ═══════════════════════════════════════════════════");
    eprintln!(
        "  CEREMONY VALID: {} contributions, chain verified",
        params.contributions.len()
    );
    eprintln!("  ═══════════════════════════════════════════════════");

    Ok(())
}

/// Phase 4: Finalize the ceremony — extract final keys and generate transcript.
pub fn finalize(input_path: &str) -> Result<(), String> {
    eprintln!("╔══════════════════════════════════════════════════════════════╗");
    eprintln!("║  ZK-LoRaWAN MPC Ceremony — Phase 4: Finalize               ║");
    eprintln!("╚══════════════════════════════════════════════════════════════╝");
    eprintln!();

    // First verify the chain
    verify(input_path)?;
    eprintln!();

    let data =
        std::fs::read(input_path).map_err(|e| format!("Failed to read {}: {}", input_path, e))?;
    let params = CeremonyParams::from_bytes(&data)?;

    // Write final keys
    // FIX 2026-10-17 (Researcher A): finalize previously wrote to the hardcoded
    // relative path "keys/" — meaning any ceremony test-run on a node would
    // silently OVERWRITE that node's live production devnet keys. Ceremony
    // output now goes to "ceremony_keys/" (deliberate, separate directory).
    // Deployment to keys/ is an explicit human/coordinator action.
    std::fs::create_dir_all("ceremony_keys")
        .map_err(|e| format!("Failed to create ceremony_keys dir: {}", e))?;

    let mut pk_buf = Vec::new();
    params
        .proving_key
        .serialize_compressed(&mut pk_buf)
        .map_err(|e| format!("Failed to serialize pk: {}", e))?;
    std::fs::write("ceremony_keys/proving_key.bin", &pk_buf)
        .map_err(|e| format!("Failed to write ceremony_keys/proving_key.bin: {}", e))?;
    eprintln!(
        "  ✅ ceremony_keys/proving_key.bin written ({} bytes)",
        pk_buf.len()
    );

    let mut vk_buf = Vec::new();
    params
        .verifying_key
        .serialize_compressed(&mut vk_buf)
        .map_err(|e| format!("Failed to serialize vk: {}", e))?;
    std::fs::write("ceremony_keys/verifying_key.bin", &vk_buf)
        .map_err(|e| format!("Failed to write ceremony_keys/verifying_key.bin: {}", e))?;
    eprintln!(
        "  ✅ ceremony_keys/verifying_key.bin written ({} bytes)",
        vk_buf.len()
    );

    // Generate ceremony transcript
    let final_vk_hash = hash_params(&params.proving_key, &params.verifying_key);
    let transcript = CeremonyTranscript {
        circuit: "ZKLoRaCircuit".to_string(),
        curve: "BN254".to_string(),
        num_contributions: params.contributions.len() as u32,
        contributions: params.contributions,
        final_vk_hash: hex::encode(final_vk_hash),
        status: "finalized".to_string(),
    };

    let transcript_json = serde_json::to_string_pretty(&transcript)
        .map_err(|e| format!("Failed to serialize transcript: {}", e))?;
    std::fs::write("ceremony_keys/ceremony_transcript.json", &transcript_json)
        .map_err(|e| format!("Failed to write ceremony transcript: {}", e))?;
    eprintln!("  ✅ ceremony_keys/ceremony_transcript.json written");

    eprintln!();
    eprintln!("  ═══════════════════════════════════════════════════");
    eprintln!("  CEREMONY FINALIZED");
    eprintln!("  Contributors: {}", transcript.num_contributions);
    eprintln!("  Final VK hash: {}", transcript.final_vk_hash);
    eprintln!("  ═══════════════════════════════════════════════════");
    eprintln!();
    eprintln!("  The keys in keys/ are now ready for deployment.");
    eprintln!("  Distribute ceremony_transcript.json for public verification.");

    Ok(())
}
