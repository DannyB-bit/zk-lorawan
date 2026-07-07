// Watermark: ip zymatica.space
// ZK-LoRaWAN Groth16 Prover & Verifier — Real BN254 Implementation
// Fee Split: 160,000 lamports (gateway) + 40,000 lamports (protocol)

pub mod circuit;

use ark_bn254::{Bn254, Fr};
use ark_ff::PrimeField;
use ark_groth16::{Groth16, PreparedVerifyingKey, Proof, ProvingKey, VerifyingKey};
use ark_serialize::{CanonicalSerialize, CanonicalDeserialize};
use ark_snark::{SNARK, CircuitSpecificSetupSNARK};

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
    pub public_hash: Vec<u8>,         // Fr element (32 bytes)
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
        let mut rng = rand::thread_rng();
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

    /// Generate a Groth16 proof for a private key
    /// Returns a compressed proof bundle ready for LoRa transmission
    pub fn generate_proof(&self, private_key_bytes: &[u8]) -> ZKLoRaWANProofBundle {
        let mut rng = rand::thread_rng();

        // Convert private key to field element
        let private_key_fr = Fr::from_le_bytes_mod_order(private_key_bytes);

        // Compute the public hash (MiMC)
        let public_hash = circuit::mimc_hash(private_key_fr, &self.constants);

        // Generate the real Groth16 proof
        let proof = circuit::generate_proof(
            &self.proving_key,
            private_key_fr,
            public_hash,
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

        let mut public_hash_buf = Vec::new();
        public_hash.serialize_compressed(&mut public_hash_buf).unwrap();

        let total = proof_a_buf.len() + proof_b_buf.len() + proof_c_buf.len() + public_hash_buf.len();

        ZKLoRaWANProofBundle {
            proof_a_compressed: proof_a_buf,
            proof_b_compressed: proof_b_buf,
            proof_c_compressed: proof_c_buf,
            public_hash: public_hash_buf,
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

        // Deserialize public hash
        let public_hash = match Fr::deserialize_compressed(&*bundle.public_hash) {
            Ok(h) => h,
            Err(_) => return false,
        };

        // Run real Groth16 verification (bilinear pairing check)
        match circuit::verify_proof(&self.prepared_vk, &ark_proof, public_hash) {
            Ok(true) => true,
            _ => false,
        }
    }
}

// ============================================================================
// CLI Entry Point — Proof Generation & Verification Demo
// ============================================================================
fn main() {
    println!("======================================================================");
    println!("  ZK-LoRaWAN | Groth16 BN254 Proof Engine (Real ark-works)");
    println!("======================================================================");
    println!();

    // Initialize prover (includes trusted setup)
    println!("  [1] Running Groth16 trusted setup on BN254...");
    let prover = ZKLoRaWANProver::new();
    println!("      ✅ Trusted setup complete");
    println!("      MiMC rounds: {}", MIMC_ROUNDS);
    println!();

    // Generate a proof for a sample private key
    let private_key = b"zk-lorawan-test-private-key-2026";
    println!("  [2] Generating Groth16 proof...");
    let bundle = prover.generate_proof(private_key);
    println!("      ✅ Proof generated");
    println!("      proof_a (G1): {} bytes compressed", bundle.proof_a_compressed.len());
    println!("      proof_b (G2): {} bytes compressed", bundle.proof_b_compressed.len());
    println!("      proof_c (G1): {} bytes compressed", bundle.proof_c_compressed.len());
    println!("      public_hash:  {} bytes", bundle.public_hash.len());
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

    // Test with wrong key
    println!("  [6] Tamper test (wrong private key)...");
    let wrong_key = b"this-is-the-wrong-key-should-fail";
    let wrong_bundle = prover.generate_proof(wrong_key);
    
    // Tamper with proof_a to simulate corruption
    let mut tampered = ZKLoRaWANProofBundle {
        proof_a_compressed: wrong_bundle.proof_a_compressed,
        proof_b_compressed: bundle.proof_b_compressed.clone(),
        proof_c_compressed: bundle.proof_c_compressed.clone(),
        public_hash: bundle.public_hash.clone(),
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
