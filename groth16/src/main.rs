// Watermark: ip zymatica.space
// ZK-LoRaWAN Groth16 Prover & Verifier — Real BN254 Implementation
// Fee Split: 100,000 lamports (gateway) + 50,000 lamports (protocol)

pub mod circuit;

use ark_bn254::{Bn254, Fr};
use ark_ff::PrimeField;
use ark_groth16::{Groth16, PreparedVerifyingKey, Proof, ProvingKey, VerifyingKey};
use ark_serialize::{CanonicalSerialize, CanonicalDeserialize};
use ark_snark::{SNARK, CircuitSpecificSetupSNARK};
use rand::SeedableRng;
use rand::rngs::StdRng;

// ============================================================================
// ZK-LoRaWAN Protocol Constants
// ============================================================================
pub const PROTOCOL_FEE_LAMPORTS: u64 = 50_000;
pub const GATEWAY_REWARD_LAMPORTS: u64 = 100_000;
pub const TOTAL_FEE_LAMPORTS: u64 = PROTOCOL_FEE_LAMPORTS + GATEWAY_REWARD_LAMPORTS;
pub const MIMC_ROUNDS: usize = 10;

// ============================================================================
// ZK-LoRaWAN Proof Bundle (serialized for LoRa transmission)
// ============================================================================
pub struct ZKLoRaWANProofBundle {
    pub proof_a_compressed: Vec<u8>,  // G1 point (32 bytes compressed)
    pub proof_b_compressed: Vec<u8>,  // G2 point (64 bytes compressed)
    pub proof_c_compressed: Vec<u8>,  // G1 point (32 bytes compressed)
    pub identity_hash: Vec<u8>,       // Fr element (32 bytes)
    pub nullifier_hash: Vec<u8>,      // Fr element (32 bytes)
    pub attestation_hash: Vec<u8>,    // Fr element (32 bytes)
    pub ciphertext_hash: Vec<u8>,     // Fr element (32 bytes)
    pub total_bytes: usize,
}

// ============================================================================
// ZK-LoRaWAN Prover (generates real Groth16 proofs for LoRa packets)
// ============================================================================
pub struct ZKLoRaWANProver {
    pub proving_key: ProvingKey<Bn254>,
    pub verifying_key: VerifyingKey<Bn254>,
    pub prepared_vk: PreparedVerifyingKey<Bn254>,
    pub constants: Vec<Fr>,
}

impl ZKLoRaWANProver {
    /// Initialize the prover with a trusted setup
    pub fn new() -> Self {
        let mut rng = StdRng::from_seed([42u8; 32]);
        let constants = circuit::generate_mimc_constants(MIMC_ROUNDS);
        let (pk, vk) = circuit::setup_keys(&mut rng, constants.clone())
            .expect("Trusted setup failed");
        let prepared_vk = ark_groth16::prepare_verifying_key(&vk);

        ZKLoRaWANProver {
            proving_key: pk,
            verifying_key: vk,
            prepared_vk,
            constants,
        }
    }

    /// Generate a Groth16 proof for private key, decryption key, coordinate value, and firmware hash
    /// Returns a compressed proof bundle ready for LoRa transmission
    pub fn generate_proof(
        &self,
        private_key_bytes: &[u8],
        decryption_key_bytes: &[u8],
        coordinate_val: u64,
        firmware_hash_bytes: &[u8],
    ) -> ZKLoRaWANProofBundle {
        let mut rng = rand::thread_rng();

        // Convert inputs to field elements
        let private_key_fr = Fr::from_le_bytes_mod_order(private_key_bytes);
        let decryption_key_fr = Fr::from_le_bytes_mod_order(decryption_key_bytes);
        let coordinate_fr = Fr::from(coordinate_val);
        let firmware_hash_fr = Fr::from_le_bytes_mod_order(firmware_hash_bytes);

        // Compute the public hashes
        let identity_hash = circuit::mimc_hash(private_key_fr, None, &self.constants);
        let nullifier_hash = circuit::mimc_hash(private_key_fr, Some(Fr::from(9999u64)), &self.constants);
        let attestation_hash = circuit::mimc_hash(private_key_fr, Some(firmware_hash_fr), &self.constants);
        let ciphertext_hash = circuit::mimc_hash(decryption_key_fr, Some(coordinate_fr), &self.constants);

        // Generate the real Groth16 proof
        let proof = circuit::generate_proof(
            &self.proving_key,
            private_key_fr,
            decryption_key_fr,
            coordinate_fr,
            firmware_hash_fr,
            identity_hash,
            nullifier_hash,
            attestation_hash,
            ciphertext_hash,
            self.constants.clone(),
            &mut rng,
        ).expect("Proof generation failed");

        // Serialize proof points to compressed form
        let mut proof_a_buf = Vec::new();
        proof.a.serialize_compressed(&mut proof_a_buf).unwrap();

        let mut proof_b_buf = Vec::new();
        proof.b.serialize_compressed(&mut proof_b_buf).unwrap();

        let mut proof_c_buf = Vec::new();
        proof.c.serialize_compressed(&mut proof_c_buf).unwrap();

        let mut identity_hash_buf = Vec::new();
        identity_hash.serialize_compressed(&mut identity_hash_buf).unwrap();

        let mut nullifier_hash_buf = Vec::new();
        nullifier_hash.serialize_compressed(&mut nullifier_hash_buf).unwrap();

        let mut attestation_hash_buf = Vec::new();
        attestation_hash.serialize_compressed(&mut attestation_hash_buf).unwrap();

        let mut ciphertext_hash_buf = Vec::new();
        ciphertext_hash.serialize_compressed(&mut ciphertext_hash_buf).unwrap();

        let total = proof_a_buf.len()
            + proof_b_buf.len()
            + proof_c_buf.len()
            + identity_hash_buf.len()
            + nullifier_hash_buf.len()
            + attestation_hash_buf.len()
            + ciphertext_hash_buf.len();

        ZKLoRaWANProofBundle {
            proof_a_compressed: proof_a_buf,
            proof_b_compressed: proof_b_buf,
            proof_c_compressed: proof_c_buf,
            identity_hash: identity_hash_buf,
            nullifier_hash: nullifier_hash_buf,
            attestation_hash: attestation_hash_buf,
            ciphertext_hash: ciphertext_hash_buf,
            total_bytes: total,
        }
    }

    /// Verify a proof bundle (used by gateway)
    pub fn verify_bundle(&self, bundle: &ZKLoRaWANProofBundle) -> bool {
        // Deserialize proof points
        let proof_a = match ark_bn254::G1Affine::deserialize_compressed(&*bundle.proof_a_compressed) {
            Ok(p) => p,
            Err(_) => return false,
        };
        let proof_b = match ark_bn254::G2Affine::deserialize_compressed(&*bundle.proof_b_compressed) {
            Ok(p) => p,
            Err(_) => return false,
        };
        let proof_c = match ark_bn254::G1Affine::deserialize_compressed(&*bundle.proof_c_compressed) {
            Ok(p) => p,
            Err(_) => return false,
        };

        let ark_proof = Proof { a: proof_a, b: proof_b, c: proof_c };

        // Deserialize public hashes
        let identity_hash = match Fr::deserialize_compressed(&*bundle.identity_hash) {
            Ok(h) => h,
            Err(_) => return false,
        };
        let nullifier_hash = match Fr::deserialize_compressed(&*bundle.nullifier_hash) {
            Ok(h) => h,
            Err(_) => return false,
        };
        let attestation_hash = match Fr::deserialize_compressed(&*bundle.attestation_hash) {
            Ok(h) => h,
            Err(_) => return false,
        };
        let ciphertext_hash = match Fr::deserialize_compressed(&*bundle.ciphertext_hash) {
            Ok(h) => h,
            Err(_) => return false,
        };

        // Run real Groth16 verification (bilinear pairing check)
        match circuit::verify_proof(
            &self.prepared_vk,
            &ark_proof,
            identity_hash,
            nullifier_hash,
            attestation_hash,
            ciphertext_hash,
        ) {
            Ok(true) => true,
            _ => false,
        }
    }
}

fn to_solana_g1(p: &ark_bn254::G1Affine) -> [u8; 64] {
    let mut bytes = vec![];
    p.serialize_uncompressed(&mut bytes).unwrap();
    let mut solana_bytes = [0u8; 64];
    for i in 0..32 {
        solana_bytes[i] = bytes[31 - i];       // reverse x to big-endian
        solana_bytes[32 + i] = bytes[63 - i];  // reverse y to big-endian
    }
    solana_bytes
}

fn to_solana_g2(p: &ark_bn254::G2Affine) -> [u8; 128] {
    let mut bytes = vec![];
    p.serialize_uncompressed(&mut bytes).unwrap();
    let mut solana_bytes = [0u8; 128];
    for i in 0..32 {
        solana_bytes[i] = bytes[63 - i];       // X_1 (x.c1) big-endian
        solana_bytes[32 + i] = bytes[31 - i];  // X_0 (x.c0) big-endian
        solana_bytes[64 + i] = bytes[127 - i]; // Y_1 (y.c1) big-endian
        solana_bytes[96 + i] = bytes[95 - i];  // Y_0 (y.c0) big-endian
    }
    solana_bytes
}

// ============================================================================
// CLI Entry Point — Proof Generation & Verification Demo
// ============================================================================
fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 && args[1] == "print-vk" {
        let prover = ZKLoRaWANProver::new();
        let vk = &prover.verifying_key;
        println!("vk_alpha: {}", hex::encode(to_solana_g1(&vk.alpha_g1)));
        println!("vk_beta: {}", hex::encode(to_solana_g2(&vk.beta_g2)));
        println!("vk_gamma: {}", hex::encode(to_solana_g2(&vk.gamma_g2)));
        println!("vk_delta: {}", hex::encode(to_solana_g2(&vk.delta_g2)));
        for (i, ic) in vk.gamma_abc_g1.iter().enumerate() {
            println!("vk_ic[{}]: {}", i, hex::encode(to_solana_g1(ic)));
        }
        std::process::exit(0);
    }

    if args.len() > 1 && args[1] == "verify" {
        if args.len() < 9 {
            eprintln!("Usage: zk_lorawan_prove verify <proof_a> <proof_b> <proof_c> <identity_hash> <nullifier_hash> <attestation_hash> <ciphertext_hash>");
            std::process::exit(2);
        }
        let proof_a_bytes = hex::decode(&args[2]).expect("Invalid proof_a hex");
        let proof_b_bytes = hex::decode(&args[3]).expect("Invalid proof_b hex");
        let proof_c_bytes = hex::decode(&args[4]).expect("Invalid proof_c hex");
        let identity_bytes = hex::decode(&args[5]).expect("Invalid identity_hash hex");
        let nullifier_bytes = hex::decode(&args[6]).expect("Invalid nullifier_hash hex");
        let attestation_bytes = hex::decode(&args[7]).expect("Invalid attestation_hash hex");
        let ciphertext_bytes = hex::decode(&args[8]).expect("Invalid ciphertext_hash hex");

        let bundle = ZKLoRaWANProofBundle {
            proof_a_compressed: proof_a_bytes,
            proof_b_compressed: proof_b_bytes,
            proof_c_compressed: proof_c_bytes,
            identity_hash: identity_bytes,
            nullifier_hash: nullifier_bytes,
            attestation_hash: attestation_bytes,
            ciphertext_hash: ciphertext_bytes,
            total_bytes: 0,
        };

        let prover = ZKLoRaWANProver::new();
        let is_valid = prover.verify_bundle(&bundle);
        if is_valid {
            println!("VALID");
            std::process::exit(0);
        } else {
            println!("INVALID");
            std::process::exit(1);
        }
    }

    println!("======================================================================");
    println!("  ZK-LoRaWAN | Groth16 BN254 Proof Engine (Real ark-works)");
    println!("  Proving Balance Identity + Nullifiers + Micro-TEE + zk-VDE");
    println!("======================================================================");
    println!();

    // Initialize prover (includes trusted setup)
    println!("  [1] Running Groth16 trusted setup on BN254...");
    let prover = ZKLoRaWANProver::new();
    println!("      ✅ Trusted setup complete");
    println!("      MiMC rounds: {}", MIMC_ROUNDS);
    println!();

    // Generate a proof for sample witnesses
    let private_key = b"zk-lorawan-test-private-key-2026";
    let decryption_key = b"zk-lorawan-decryption-key-secret";
    let coordinate_val = 123456789u64;
    let firmware_hash = b"enclave-firmware-version-v1.0.2";

    println!("  [2] Generating Groth16 proof...");
    let bundle = prover.generate_proof(private_key, decryption_key, coordinate_val, firmware_hash);
    println!("      ✅ Proof generated");
    println!("      proof_a (G1): {} bytes compressed", bundle.proof_a_compressed.len());
    println!("      proof_b (G2): {} bytes compressed", bundle.proof_b_compressed.len());
    println!("      proof_c (G1): {} bytes compressed", bundle.proof_c_compressed.len());
    println!("      identity_hash:{} bytes", bundle.identity_hash.len());
    println!("      nullifier_hash:{} bytes", bundle.nullifier_hash.len());
    println!("      attestation_hash:{} bytes", bundle.attestation_hash.len());
    println!("      ciphertext_hash:{} bytes", bundle.ciphertext_hash.len());
    println!("      TOTAL:        {} bytes", bundle.total_bytes);
    println!();

    // Verify the proof
    println!("  [3] Verifying proof (bilinear pairing check)...");
    let is_valid = prover.verify_bundle(&bundle);
    println!("      Verification result: {}", if is_valid { "✅ VALID" } else { "❌ INVALID" });
    println!();

    // Check LoRa MTU fit
    let lora_mtu = 255;
    let overhead = 3 + 6 + 8; // frame header + coordinates + receiver_tag
    let available = lora_mtu - overhead;
    let fits = bundle.total_bytes <= available;
    println!("  [4] LoRa MTU check:");
    println!("      LoRa MTU:       {} bytes", lora_mtu);
    println!("      Frame overhead: {} bytes (header + coords + tag)", overhead);
    println!("      Available:      {} bytes", available);
    println!("      Proof size:     {} bytes", bundle.total_bytes);
    println!("      Fits in frame:  {}", if fits { "✅ YES" } else { "⚠️  Needs LLD-AC compression" });
    println!();

    // Fee split display
    println!("  [5] ZK-LoRaWAN Fee Split:");
    println!("      Gateway reward:  {} lamports (${:.4})", GATEWAY_REWARD_LAMPORTS, GATEWAY_REWARD_LAMPORTS as f64 / 1_000_000_000.0 * 150.0);
    println!("      Protocol fee:    {} lamports (${:.4})", PROTOCOL_FEE_LAMPORTS, PROTOCOL_FEE_LAMPORTS as f64 / 1_000_000_000.0 * 150.0);
    println!("      Total per packet:{} lamports (${:.4})", TOTAL_FEE_LAMPORTS, TOTAL_FEE_LAMPORTS as f64 / 1_000_000_000.0 * 150.0);
    println!();

    // Test with wrong key / tampered inputs
    println!("  [6] Tamper test (wrong inputs)...");
    let wrong_key = b"this-is-the-wrong-key-should-fail";
    let wrong_bundle = prover.generate_proof(wrong_key, decryption_key, coordinate_val, firmware_hash);
    
    // Tamper with proof_a to simulate corruption
    let mut tampered = ZKLoRaWANProofBundle {
        proof_a_compressed: wrong_bundle.proof_a_compressed,
        proof_b_compressed: bundle.proof_b_compressed.clone(),
        proof_c_compressed: bundle.proof_c_compressed.clone(),
        identity_hash: bundle.identity_hash.clone(),
        nullifier_hash: bundle.nullifier_hash.clone(),
        attestation_hash: bundle.attestation_hash.clone(),
        ciphertext_hash: bundle.ciphertext_hash.clone(),
        total_bytes: bundle.total_bytes,
    };
    // Flip a byte to corrupt
    if !tampered.proof_a_compressed.is_empty() {
        tampered.proof_a_compressed[0] ^= 0xFF;
    }
    let tamper_valid = prover.verify_bundle(&tampered);
    println!("      Tampered proof result: {}", if !tamper_valid { "✅ CORRECTLY REJECTED" } else { "❌ SHOULD HAVE FAILED" });
    println!();

    if is_valid && !tamper_valid {
        println!("  🎉 ALL CHECKS PASSED — Groth16 BN254 engine operational");
    } else {
        println!("  ❌ VERIFICATION FAILED");
    }
    println!();
    println!("======================================================================");
}
