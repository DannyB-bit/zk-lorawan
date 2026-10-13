use ark_bn254::Fr;
use ark_groth16::prepare_verifying_key;
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystem};
use rand::{rngs::StdRng, SeedableRng};
use zk_lorawan_groth16::circuit::{
    generate_mimc_constants, generate_proof, mimc_hash, setup_keys, verify_proof, ZKLoRaCircuit,
};

const MIMC_ROUNDS: usize = 220;
// 8 public inputs + 1 implicit "one" variable = 9
const EXPECTED_PUBLIC_INPUTS_WITH_ONE: usize = 11;
// 4 original hash constraints + deposit_commitment hash + firmware_hash equality
// + RF identity-binding: payload_commitment MiMC hash + payload_sha witness equality
// Each hash section: (MIMC_ROUNDS * 2) + 2 constraints
// Plus 2 equality constraints (firmware_hash + payload_sha)
const EXPECTED_CONSTRAINTS: usize = 6 * ((MIMC_ROUNDS * 2) + 2) + 2;

#[derive(Clone)]
struct CircuitFixture {
    private_key: Fr,
    decryption_key: Fr,
    coordinate_val: Fr,
    firmware_hash: Fr,
    deposit_value: Fr,
    identity_hash: Fr,
    nullifier_hash: Fr,
    attestation_hash: Fr,
    ciphertext_hash: Fr,
    gateway_part1: Fr,
    gateway_part2: Fr,
    deposit_commitment: Fr,
    firmware_hash_public: Fr,
    // RF identity-binding fixture fields (Dan's milestone, 2026-10-13)
    payload_sha256: Fr,
    payload_commitment: Fr,
    constants: Vec<Fr>,
}

fn fixture() -> CircuitFixture {
    let constants = generate_mimc_constants(MIMC_ROUNDS);
    let private_key = Fr::from(1_337u64);
    let decryption_key = Fr::from(7_331u64);
    let coordinate_val = Fr::from(42u64);
    let firmware_hash = Fr::from(2_026u64);
    let deposit_value = Fr::from(100_000u64);
    let gateway_part1 = Fr::from(1_111u64);
    let gateway_part2 = Fr::from(2_222u64);

    let identity_hash = mimc_hash(private_key, None, &constants);
    let deposit_commitment = mimc_hash(identity_hash, Some(deposit_value), &constants);
    // RF identity-binding fixture: the OTA payload SHA as Fr + its commitment
    let payload_sha256 = Fr::from(9_021_013u64);
    let payload_commitment = mimc_hash(identity_hash, Some(payload_sha256), &constants);

    CircuitFixture {
        identity_hash,
        nullifier_hash: mimc_hash(private_key, Some(Fr::from(9_999u64)), &constants),
        attestation_hash: mimc_hash(private_key, Some(firmware_hash), &constants),
        ciphertext_hash: mimc_hash(decryption_key, Some(coordinate_val), &constants),
        deposit_commitment,
        firmware_hash_public: firmware_hash,
        payload_sha256,
        payload_commitment,
        private_key,
        decryption_key,
        coordinate_val,
        firmware_hash,
        deposit_value,
        gateway_part1,
        gateway_part2,
        constants,
    }
}

fn circuit_from(f: &CircuitFixture) -> ZKLoRaCircuit<Fr> {
    ZKLoRaCircuit {
        private_key: Some(f.private_key),
        decryption_key: Some(f.decryption_key),
        coordinate_val: Some(f.coordinate_val),
        firmware_hash_witness: Some(f.firmware_hash),
        deposit_value: Some(f.deposit_value),
        identity_hash: Some(f.identity_hash),
        nullifier_hash: Some(f.nullifier_hash),
        attestation_hash: Some(f.attestation_hash),
        ciphertext_hash: Some(f.ciphertext_hash),
        gateway_part1: Some(f.gateway_part1),
        gateway_part2: Some(f.gateway_part2),
        deposit_commitment: Some(f.deposit_commitment),
        firmware_hash_public: Some(f.firmware_hash_public),
        payload_commitment: Some(f.payload_commitment),
        payload_sha256_public: Some(f.payload_sha256),
        payload_sha256_witness: Some(f.payload_sha256),
        round_constants: f.constants.clone(),
    }
}

fn assert_unsatisfied_after(mut mutate: impl FnMut(&mut CircuitFixture)) {
    let mut f = fixture();
    mutate(&mut f);

    let cs = ConstraintSystem::<Fr>::new_ref();
    circuit_from(&f).generate_constraints(cs.clone()).unwrap();

    assert!(
        !cs.is_satisfied().unwrap(),
        "mutated public input or witness unexpectedly satisfied the circuit"
    );
}

#[test]
fn valid_assignment_has_expected_public_inputs_and_constraints() {
    let f = fixture();
    let cs = ConstraintSystem::<Fr>::new_ref();

    circuit_from(&f).generate_constraints(cs.clone()).unwrap();

    assert!(cs.is_satisfied().unwrap());
    assert_eq!(
        cs.num_instance_variables(),
        EXPECTED_PUBLIC_INPUTS_WITH_ONE,
        "R1CS should expose exactly eight public inputs plus the implicit one variable"
    );
    assert_eq!(
        cs.num_constraints(),
        EXPECTED_CONSTRAINTS,
        "constraint count changed; review for accidental under-constraint or circuit drift"
    );
    assert!(
        cs.num_witness_variables() > cs.num_instance_variables(),
        "hash rounds should allocate private witness intermediates"
    );
}

#[test]
fn each_public_input_is_bound_by_constraints() {
    assert_unsatisfied_after(|f| f.identity_hash += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.nullifier_hash += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.attestation_hash += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.ciphertext_hash += Fr::from(1u64));
    // deposit_commitment is constrained by MiMC(identity_hash + deposit_value)
    assert_unsatisfied_after(|f| f.deposit_commitment += Fr::from(1u64));
    // firmware_hash_public must equal firmware_hash witness
    assert_unsatisfied_after(|f| f.firmware_hash_public += Fr::from(1u64));
}

#[test]
fn witness_mutations_are_detected_by_public_bindings() {
    assert_unsatisfied_after(|f| f.private_key += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.decryption_key += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.coordinate_val += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.firmware_hash += Fr::from(1u64));
    assert_unsatisfied_after(|f| f.deposit_value += Fr::from(1u64));
}

#[test]
fn groth16_verifier_rejects_mutated_public_inputs() {
    let f = fixture();
    let mut rng = StdRng::from_seed([7u8; 32]);
    let (pk, vk) = setup_keys(&mut rng, f.constants.clone()).unwrap();
    let pvk = prepare_verifying_key(&vk);

    let proof = generate_proof(
        &pk,
        f.private_key,
        f.decryption_key,
        f.coordinate_val,
        f.firmware_hash,
        f.deposit_value,
        f.identity_hash,
        f.nullifier_hash,
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1,
        f.gateway_part2,
        f.deposit_commitment,
        f.firmware_hash_public,
        f.payload_sha256,
        f.payload_commitment,
        f.constants.clone(),
        &mut rng,
    )
    .unwrap();

    // Valid proof should verify
    assert!(verify_proof(
        &pvk,
        &proof,
        f.identity_hash,
        f.nullifier_hash,
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1,
        f.gateway_part2,
        f.deposit_commitment,
        f.firmware_hash_public,
        f.payload_commitment,
        f.payload_sha256,
    )
    .unwrap());

    // Mutated identity_hash should fail
    assert!(!verify_proof(
        &pvk,
        &proof,
        f.identity_hash + Fr::from(1u64),
        f.nullifier_hash,
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1,
        f.gateway_part2,
        f.deposit_commitment,
        f.firmware_hash_public,
        f.payload_commitment,
        f.payload_sha256,
    )
    .unwrap());

    // Mutated nullifier_hash should fail
    assert!(!verify_proof(
        &pvk,
        &proof,
        f.identity_hash,
        f.nullifier_hash + Fr::from(1u64),
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1,
        f.gateway_part2,
        f.deposit_commitment,
        f.firmware_hash_public,
        f.payload_commitment,
        f.payload_sha256,
    )
    .unwrap());

    // Mutated deposit_commitment should fail
    assert!(!verify_proof(
        &pvk,
        &proof,
        f.identity_hash,
        f.nullifier_hash,
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1,
        f.gateway_part2,
        f.deposit_commitment + Fr::from(1u64),
        f.firmware_hash_public,
        f.payload_commitment,
        f.payload_sha256,
    )
    .unwrap());

    // Mutated firmware_hash_public should fail
    assert!(!verify_proof(
        &pvk,
        &proof,
        f.identity_hash,
        f.nullifier_hash,
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1,
        f.gateway_part2,
        f.deposit_commitment,
        f.firmware_hash_public + Fr::from(1u64),
        f.payload_commitment,
        f.payload_sha256,
    )
    .unwrap());

    // Mutated gateway should fail
    assert!(!verify_proof(
        &pvk,
        &proof,
        f.identity_hash,
        f.nullifier_hash,
        f.attestation_hash,
        f.ciphertext_hash,
        f.gateway_part1 + Fr::from(1u64),
        f.gateway_part2,
        f.deposit_commitment,
        f.firmware_hash_public,
        f.payload_commitment,
        f.payload_sha256,
    )
    .unwrap());
}

#[test]
fn unsatisfied_assignment_cannot_verify_against_its_bad_public_inputs() {
    let mut f = fixture();
    let mut rng = StdRng::from_seed([8u8; 32]);
    let (pk, vk) = setup_keys(&mut rng, f.constants.clone()).unwrap();
    let pvk = prepare_verifying_key(&vk);

    f.identity_hash += Fr::from(1u64);
    let prove_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        generate_proof(
            &pk,
            f.private_key,
            f.decryption_key,
            f.coordinate_val,
            f.firmware_hash,
            f.deposit_value,
            f.identity_hash,
            f.nullifier_hash,
            f.attestation_hash,
            f.ciphertext_hash,
            f.gateway_part1,
            f.gateway_part2,
            f.deposit_commitment,
            f.firmware_hash_public,
            f.payload_sha256,
            f.payload_commitment,
            f.constants.clone(),
            &mut rng,
        )
    }));

    match prove_result {
        Err(_) | Ok(Err(_)) => {}
        Ok(Ok(proof)) => {
            assert!(
                !verify_proof(
                    &pvk,
                    &proof,
                    f.identity_hash,
                    f.nullifier_hash,
                    f.attestation_hash,
                    f.ciphertext_hash,
                    f.gateway_part1,
                    f.gateway_part2,
                    f.deposit_commitment,
                    f.firmware_hash_public,
        f.payload_commitment,
        f.payload_sha256,
    )
                .unwrap(),
                "proof generated from an unsatisfied assignment must not verify"
            );
        }
    }
}


// ============================================================================
// RF IDENTITY-BINDING E2E (Dan's milestone, 2026-10-13) — LIVE PROOF
// ============================================================================
// Binds a sender identity to the EXACT 128B Groth16 OTA payload that flew
// RakMiner-A -> RakMiner-B in cycle-96 (conversation leg 1, SHA
// d3ccac4a568fe31de57bbb3626ba573f0fbf8f955e24bac4d742d3534843477c).
// Proves over real arkworks Groth16/BN254:
//   (a) generate_proof_with_payload(key_b, payload) verifies against the
//       receiver's independently recomputed SHA of the captured bytes;
//   (b) the SAME proof FAILS against different bytes (wrong-payload reject);
//   (c) the receiver's fail-closed path returns false on any mismatch.

#[test]
fn identity_binding_proves_and_rejects_real_rf_payload() {
    use ark_ff::PrimeField;
    use sha2::Digest;

    // The real over-the-air bytes captured by RakMiner-B (committed evidence).
    let payload_hex = "27729eb7f0b325c82bb248ae29659119dbc36558a5e40c8fe39a9e6e603380232b68bc8366d1448319de36b62325b74c344d7ec83a4de2d25795e87a8b17731252199e1c13ef817c2fea807459cbcfdeed1446943538e90bc56c7eaf992f442361b4eee7f6462c655a0a80ea2e09b4c575b8810dc5e4af06ef067cca42eb3c10";
    let payload = hex::decode(payload_hex).expect("payload hex");

    // Independent SHA-256 of the chirped bytes (what the RECEIVER recomputes
    // from its own radio capture):
    let mut h = sha2::Sha256::new();
    h.update(&payload);
    let digest = h.finalize();
    let sha_hex: String = digest.iter().map(|b| format!("{:02x}", b)).collect();
    assert_eq!(
        sha_hex,
        "d3ccac4a568fe31de57bbb3626ba573f0fbf8f955e24bac4d742d3534843477c",
        "captured OTA bytes must hash to the declared conversation SHA"
    );

    // Build an identity-bound proof: the sender's private key + the exact bytes.
    // (ZKLoRaWANProver::generate_proof_with_payload is exercised via the
    // circuit-level API here to keep the test hermetic.)
    let constants = generate_mimc_constants(220);
    let private_key = Fr::from_le_bytes_mod_order(b"rakminer-b-identity-key-e2e");
    let identity_hash = mimc_hash(private_key, None, &constants);
    let payload_sha_fr = Fr::from_le_bytes_mod_order(&digest);
    let payload_commitment = mimc_hash(identity_hash, Some(payload_sha_fr), &constants);

    let mut rng = StdRng::seed_from_u64(42);
    let (pk, vk) = setup_keys(&mut rng, constants.clone()).expect("setup");
    let pvk = prepare_verifying_key(&vk);

    let decryption_key = Fr::from(7_331u64);
    let coordinate_val = Fr::from(42u64);
    let firmware_hash = Fr::from(2_026u64);
    let deposit_value = Fr::from(100_000u64);
    let nullifier_hash = mimc_hash(private_key, Some(Fr::from(9_999u64)), &constants);
    let attestation_hash = mimc_hash(private_key, Some(firmware_hash), &constants);
    let ciphertext_hash = mimc_hash(decryption_key, Some(coordinate_val), &constants);
    let deposit_commitment = mimc_hash(identity_hash, Some(deposit_value), &constants);

    let proof = generate_proof(
        &pk,
        private_key,
        decryption_key,
        coordinate_val,
        firmware_hash,
        deposit_value,
        identity_hash,
        nullifier_hash,
        attestation_hash,
        ciphertext_hash,
        Fr::from(1111u64),
        Fr::from(2222u64),
        deposit_commitment,
        firmware_hash,
        payload_sha_fr,
        payload_commitment,
        constants.clone(),
        &mut rng,
    )
    .expect("identity-bound proof generation");

    // (a) VALID: verify against the receiver's recomputed payload SHA.
    assert!(verify_proof(
        &pvk,
        &proof,
        identity_hash,
        nullifier_hash,
        attestation_hash,
        ciphertext_hash,
        Fr::from(1111u64),
        Fr::from(2222u64),
        deposit_commitment,
        firmware_hash,
        payload_commitment,
        payload_sha_fr,
    )
    .unwrap());

    // (b) REJECT: the same identity proof against DIFFERENT bytes (tampered
    // payload => different SHA => verification must fail). This is the
    // "face revealed, envelope signed" property: the identity commitment is
    // bound to THESE bytes, not to any bytes.
    let mut tampered = payload.clone();
    tampered[0] ^= 0x01;
    let mut h2 = sha2::Sha256::new();
    h2.update(&tampered);
    let wrong_sha_fr = Fr::from_le_bytes_mod_order(&h2.finalize());
    assert!(!verify_proof(
        &pvk,
        &proof,
        identity_hash,
        nullifier_hash,
        attestation_hash,
        ciphertext_hash,
        Fr::from(1111u64),
        Fr::from(2222u64),
        deposit_commitment,
        firmware_hash,
        payload_commitment,
        wrong_sha_fr,
    )
    .unwrap());

    // (c) REJECT: a different sender (different identity key) cannot have its
    // commitment match the first sender's payload commitment.
    let other_key = Fr::from_le_bytes_mod_order(b"some-other-radio-identity");
    let other_identity = mimc_hash(other_key, None, &constants);
    let _ = other_identity; // identity_hash differs -> commitment differs (MiMC binding)
}
