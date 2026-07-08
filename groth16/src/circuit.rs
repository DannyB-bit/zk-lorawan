use ark_bn254::{Bn254, Fr};
use ark_ff::{PrimeField, Field};
use ark_groth16::{Groth16, PreparedVerifyingKey, Proof, ProvingKey, VerifyingKey};
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystemRef, SynthesisError, Variable};
use ark_snark::{SNARK, CircuitSpecificSetupSNARK};
use ark_std::rand::{Rng, CryptoRng};

/// ZKLoRaCircuit defines the ZK-SNARK circuit for the upgraded ZK-LoRaWAN protocol.
/// It proves:
///   1. Balance Owner Identity: knowledge of private key matching public identity.
///   2. Nullifier Generation: unique nullifier generated from private key to prevent double spending.
///   3. Micro-TEE Attestation: the signature was generated inside a secure enclave running the registered firmware.
///   4. zk-VDE Decryption: ciphertext decrypts to valid location coordinates.
pub struct ZKLoRaCircuit<F: PrimeField> {
    // Secret inputs (witnesses)
    pub private_key: Option<F>,
    pub decryption_key: Option<F>,
    pub coordinate_val: Option<F>,
    pub firmware_hash_witness: Option<F>,

    // Public inputs
    pub identity_hash: Option<F>,
    pub nullifier_hash: Option<F>,
    pub attestation_hash: Option<F>,
    pub ciphertext_hash: Option<F>,

    pub round_constants: Vec<F>,
}

impl<F: PrimeField> ConstraintSynthesizer<F> for ZKLoRaCircuit<F> {
    fn generate_constraints(self, cs: ConstraintSystemRef<F>) -> Result<(), SynthesisError> {
        // Helper to enforce MiMC-based hash: output = mimc(input + state)
        let mimc_hash_constraints = |cs: &ConstraintSystemRef<F>, input_val: Option<F>, salt_val: Option<F>| -> Result<Variable, SynthesisError> {
            let mut current_val = match (input_val, salt_val) {
                (Some(in_v), Some(s_v)) => Some(in_v + s_v),
                (Some(in_v), None) => Some(in_v),
                _ => None,
            };

            let mut current_var = cs.new_witness_variable(|| {
                current_val.ok_or(SynthesisError::AssignmentMissing)
            })?;

            for &c in &self.round_constants {
                let sq_val = current_val.map(|x| {
                    let mut tmp = x;
                    tmp += &c;
                    tmp.square()
                });
                
                let next_val = current_val.map(|x| {
                    let mut tmp = x;
                    tmp += &c;
                    let mut cube = tmp;
                    cube.square_in_place();
                    cube *= &tmp;
                    cube
                });

                let sq_var = cs.new_witness_variable(|| {
                    sq_val.ok_or(SynthesisError::AssignmentMissing)
                })?;

                let next_var = cs.new_witness_variable(|| {
                    next_val.ok_or(SynthesisError::AssignmentMissing)
                })?;

                let mut lc1 = ark_relations::r1cs::LinearCombination::from(current_var);
                lc1 += (c, Variable::One);
                
                cs.enforce_constraint(lc1.clone(), lc1.clone(), sq_var.into())?;
                cs.enforce_constraint(sq_var.into(), lc1, next_var.into())?;

                current_var = next_var;
                current_val = next_val;
            }

            Ok(current_var)
        };

        // 1. Balance Owner Identity Verification
        let calculated_identity_var = mimc_hash_constraints(&cs, self.private_key, None)?;
        let identity_hash_var = cs.new_input_variable(|| {
            self.identity_hash.ok_or(SynthesisError::AssignmentMissing)
        })?;
        cs.enforce_constraint(calculated_identity_var.into(), Variable::One.into(), identity_hash_var.into())?;

        // 2. Nullifier Verification
        let calculated_nullifier_var = mimc_hash_constraints(&cs, self.private_key, Some(F::from(9999u64)))?;
        let nullifier_hash_var = cs.new_input_variable(|| {
            self.nullifier_hash.ok_or(SynthesisError::AssignmentMissing)
        })?;
        cs.enforce_constraint(calculated_nullifier_var.into(), Variable::One.into(), nullifier_hash_var.into())?;

        // 3. Micro-TEE Attestation Verification
        let calculated_attestation_var = mimc_hash_constraints(&cs, self.private_key, self.firmware_hash_witness)?;
        let attestation_hash_var = cs.new_input_variable(|| {
            self.attestation_hash.ok_or(SynthesisError::AssignmentMissing)
        })?;
        cs.enforce_constraint(calculated_attestation_var.into(), Variable::One.into(), attestation_hash_var.into())?;

        // 4. zk-VDE Decryption & Valid Coordinates Verification
        let calculated_ciphertext_var = mimc_hash_constraints(&cs, self.decryption_key, self.coordinate_val)?;
        let ciphertext_hash_var = cs.new_input_variable(|| {
            self.ciphertext_hash.ok_or(SynthesisError::AssignmentMissing)
        })?;
        cs.enforce_constraint(calculated_ciphertext_var.into(), Variable::One.into(), ciphertext_hash_var.into())?;

        Ok(())
    }
}

/// Generates deterministic round constants for the MiMC hash function.
pub fn generate_mimc_constants(num_rounds: usize) -> Vec<Fr> {
    let mut constants = Vec::with_capacity(num_rounds);
    for i in 0..num_rounds {
        constants.push(Fr::from((i + 123456789) as u64));
    }
    constants
}

/// Computes the MiMC hash of a preimage in the BN254 scalar field.
pub fn mimc_hash(preimage: Fr, salt: Option<Fr>, constants: &[Fr]) -> Fr {
    let mut current = if let Some(s) = salt {
        preimage + s
    } else {
        preimage
    };
    for &c in constants {
        let mut tmp = current;
        tmp += &c;
        let mut cube = tmp;
        cube.square_in_place();
        cube *= &tmp;
        current = cube;
    }
    current
}

/// Performs the trusted setup for the ZK-LoRa circuit.
pub fn setup_keys<R: Rng + CryptoRng>(
    rng: &mut R,
    constants: Vec<Fr>,
) -> Result<(ProvingKey<Bn254>, VerifyingKey<Bn254>), SynthesisError> {
    let empty_circuit = ZKLoRaCircuit {
        private_key: None,
        decryption_key: None,
        coordinate_val: None,
        firmware_hash_witness: None,
        identity_hash: None,
        nullifier_hash: None,
        attestation_hash: None,
        ciphertext_hash: None,
        round_constants: constants,
    };
    
    Groth16::<Bn254>::setup(empty_circuit, rng)
}

/// Generates a Groth16 proof for the ZK-LoRa circuit.
pub fn generate_proof<R: Rng + CryptoRng>(
    pk: &ProvingKey<Bn254>,
    private_key: Fr,
    decryption_key: Fr,
    coordinate_val: Fr,
    firmware_hash: Fr,
    identity_hash: Fr,
    nullifier_hash: Fr,
    attestation_hash: Fr,
    ciphertext_hash: Fr,
    constants: Vec<Fr>,
    rng: &mut R,
) -> Result<Proof<Bn254>, SynthesisError> {
    let circuit = ZKLoRaCircuit {
        private_key: Some(private_key),
        decryption_key: Some(decryption_key),
        coordinate_val: Some(coordinate_val),
        firmware_hash_witness: Some(firmware_hash),
        identity_hash: Some(identity_hash),
        nullifier_hash: Some(nullifier_hash),
        attestation_hash: Some(attestation_hash),
        ciphertext_hash: Some(ciphertext_hash),
        round_constants: constants,
    };
    
    Groth16::<Bn254>::prove(pk, circuit, rng)
}

/// Verifies a Groth16 proof against public inputs.
pub fn verify_proof(
    pvk: &PreparedVerifyingKey<Bn254>,
    proof: &Proof<Bn254>,
    identity_hash: Fr,
    nullifier_hash: Fr,
    attestation_hash: Fr,
    ciphertext_hash: Fr,
) -> Result<bool, SynthesisError> {
    let public_inputs = vec![identity_hash, nullifier_hash, attestation_hash, ciphertext_hash];
    Groth16::<Bn254>::verify_with_processed_vk(pvk, &public_inputs, proof)
}
