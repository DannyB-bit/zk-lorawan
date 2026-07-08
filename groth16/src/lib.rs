pub mod circuit;

use ark_serialize::CanonicalDeserialize;
use ark_ff::PrimeField;
use rand::SeedableRng;
use std::sync::OnceLock;

static PREPARED_VK: OnceLock<ark_groth16::PreparedVerifyingKey<ark_bn254::Bn254>> = OnceLock::new();


/// WebAssembly-compatible verification function.
/// Takes pointers to UTF-8 hex strings for proof points and the four public input hashes,
/// decodes them, and performs the real Groth16 verification on the BN254 curve.
#[no_mangle]
pub extern "C" fn verify_zk_proof_raw(
    proof_a_hex_ptr: *const u8, proof_a_hex_len: usize,
    proof_b_hex_ptr: *const u8, proof_b_hex_len: usize,
    proof_c_hex_ptr: *const u8, proof_c_hex_len: usize,
    identity_hash_hex_ptr: *const u8, identity_hash_hex_len: usize,
    nullifier_hash_hex_ptr: *const u8, nullifier_hash_hex_len: usize,
    attestation_hash_hex_ptr: *const u8, attestation_hash_hex_len: usize,
    ciphertext_hash_hex_ptr: *const u8, ciphertext_hash_hex_len: usize,
) -> u32 {
    let proof_a_bytes_slice = unsafe { std::slice::from_raw_parts(proof_a_hex_ptr, proof_a_hex_len) };
    let proof_b_bytes_slice = unsafe { std::slice::from_raw_parts(proof_b_hex_ptr, proof_b_hex_len) };
    let proof_c_bytes_slice = unsafe { std::slice::from_raw_parts(proof_c_hex_ptr, proof_c_hex_len) };
    let identity_hash_bytes_slice = unsafe { std::slice::from_raw_parts(identity_hash_hex_ptr, identity_hash_hex_len) };
    let nullifier_hash_bytes_slice = unsafe { std::slice::from_raw_parts(nullifier_hash_hex_ptr, nullifier_hash_hex_len) };
    let attestation_hash_bytes_slice = unsafe { std::slice::from_raw_parts(attestation_hash_hex_ptr, attestation_hash_hex_len) };
    let ciphertext_hash_bytes_slice = unsafe { std::slice::from_raw_parts(ciphertext_hash_hex_ptr, ciphertext_hash_hex_len) };

    let proof_a_str = match std::str::from_utf8(proof_a_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let proof_b_str = match std::str::from_utf8(proof_b_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let proof_c_str = match std::str::from_utf8(proof_c_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let identity_hash_str = match std::str::from_utf8(identity_hash_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let nullifier_hash_str = match std::str::from_utf8(nullifier_hash_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let attestation_hash_str = match std::str::from_utf8(attestation_hash_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };
    let ciphertext_hash_str = match std::str::from_utf8(ciphertext_hash_bytes_slice) {
        Ok(s) => s,
        Err(_) => return 0,
    };

    // Strip "0x" prefix if present
    let a_hex = if proof_a_str.starts_with("0x") { &proof_a_str[2..] } else { proof_a_str };
    let b_hex = if proof_b_str.starts_with("0x") { &proof_b_str[2..] } else { proof_b_str };
    let c_hex = if proof_c_str.starts_with("0x") { &proof_c_str[2..] } else { proof_c_str };

    let proof_a_bytes = match hex::decode(a_hex) {
        Ok(b) => b,
        Err(_) => return 0,
    };
    let proof_b_bytes = match hex::decode(b_hex) {
        Ok(b) => b,
        Err(_) => return 0,
    };
    let proof_c_bytes = match hex::decode(c_hex) {
        Ok(b) => b,
        Err(_) => return 0,
    };

    let identity_bytes = match hex::decode(identity_hash_str) {
        Ok(b) => b,
        Err(_) => return 0,
    };
    let nullifier_bytes = match hex::decode(nullifier_hash_str) {
        Ok(b) => b,
        Err(_) => return 0,
    };
    let attestation_bytes = match hex::decode(attestation_hash_str) {
        Ok(b) => b,
        Err(_) => return 0,
    };
    let ciphertext_bytes = match hex::decode(ciphertext_hash_str) {
        Ok(b) => b,
        Err(_) => return 0,
    };

    let proof_a = match ark_bn254::G1Affine::deserialize_compressed(&*proof_a_bytes) {
        Ok(p) => p,
        Err(_) => return 0,
    };
    let proof_b = match ark_bn254::G2Affine::deserialize_compressed(&*proof_b_bytes) {
        Ok(p) => p,
        Err(_) => return 0,
    };
    let proof_c = match ark_bn254::G1Affine::deserialize_compressed(&*proof_c_bytes) {
        Ok(p) => p,
        Err(_) => return 0,
    };

    let ark_proof = ark_groth16::Proof {
        a: proof_a,
        b: proof_b,
        c: proof_c,
    };

    let identity_hash_fr = match ark_bn254::Fr::deserialize_compressed(&*identity_bytes) {
        Ok(h) => h,
        Err(_) => return 0,
    };
    let nullifier_hash_fr = match ark_bn254::Fr::deserialize_compressed(&*nullifier_bytes) {
        Ok(h) => h,
        Err(_) => return 0,
    };
    let attestation_hash_fr = match ark_bn254::Fr::deserialize_compressed(&*attestation_bytes) {
        Ok(h) => h,
        Err(_) => return 0,
    };
    let ciphertext_hash_fr = match ark_bn254::Fr::deserialize_compressed(&*ciphertext_bytes) {
        Ok(h) => h,
        Err(_) => return 0,
    };

    // Setup keys deterministically once and cache the prepared VK
    let prepared_vk = match PREPARED_VK.get_or_init(|| {
        let mut rng = rand::rngs::StdRng::from_seed([42u8; 32]);
        let constants = circuit::generate_mimc_constants(10);
        let (_pk, vk) = circuit::setup_keys(&mut rng, constants)
            .expect("Failed to setup keys");
        ark_groth16::prepare_verifying_key(&vk)
    }) {
        pvk => pvk,
    };

    match circuit::verify_proof(
        &prepared_vk,
        &ark_proof,
        identity_hash_fr,
        nullifier_hash_fr,
        attestation_hash_fr,
        ciphertext_hash_fr,
    ) {
        Ok(true) => 1,
        _ => 0,
    }
}

fn to_solana_g1(p: &ark_bn254::G1Affine) -> [u8; 64] {
    use ark_serialize::CanonicalSerialize;
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
    use ark_serialize::CanonicalSerialize;
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

/// Decodes compressed G1/G2 points and outputs uncompressed big-endian Solana coordinates.
#[no_mangle]
pub extern "C" fn decompress_proof_to_solana_coords(
    proof_a_comp_ptr: *const u8,
    proof_b_comp_ptr: *const u8,
    proof_c_comp_ptr: *const u8,
    proof_a_uncomp_out_ptr: *mut u8,
    proof_b_uncomp_out_ptr: *mut u8,
    proof_c_uncomp_out_ptr: *mut u8,
) -> u32 {
    let proof_a_comp = unsafe { std::slice::from_raw_parts(proof_a_comp_ptr, 32) };
    let proof_b_comp = unsafe { std::slice::from_raw_parts(proof_b_comp_ptr, 64) };
    let proof_c_comp = unsafe { std::slice::from_raw_parts(proof_c_comp_ptr, 32) };

    let p_a = match ark_bn254::G1Affine::deserialize_compressed(proof_a_comp) {
        Ok(p) => p,
        Err(_) => return 0,
    };
    let p_b = match ark_bn254::G2Affine::deserialize_compressed(proof_b_comp) {
        Ok(p) => p,
        Err(_) => return 0,
    };
    let p_c = match ark_bn254::G1Affine::deserialize_compressed(proof_c_comp) {
        Ok(p) => p,
        Err(_) => return 0,
    };

    let solana_a = to_solana_g1(&p_a);
    let solana_b = to_solana_g2(&p_b);
    let solana_c = to_solana_g1(&p_c);

    unsafe {
        std::ptr::copy_nonoverlapping(solana_a.as_ptr(), proof_a_uncomp_out_ptr, 64);
        std::ptr::copy_nonoverlapping(solana_b.as_ptr(), proof_b_uncomp_out_ptr, 128);
        std::ptr::copy_nonoverlapping(solana_c.as_ptr(), proof_c_uncomp_out_ptr, 64);
    }

    1
}
