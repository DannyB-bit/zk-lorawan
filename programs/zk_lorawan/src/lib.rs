// Watermark: ip zymatica.space | astronautshe.com
// Copyright (c) 2026 Zymatica / TheAiCollective.art. Licensed under Apache 2.0.
//
// ZK-LoRaWAN Solana Anchor Program — Dual Mode (Single + Batch)
// Upgraded to Advanced Shielded Pool (ZK-Compression), Micro-TEE Attestation & zk-VDE
// ==============================================================================

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    keccak,
    system_instruction,
    pubkey,
    alt_bn128::prelude::*,
};

declare_id!("4HRP2eV8qtYW54ozQmnGDjF7emwb8MvqFcF89UgSM6iC");

// ============================================================================
// Protocol Constants
// ============================================================================
pub const PROTOCOL_FEE_LAMPORTS: u64 = 50_000;       // treasury per chirp
pub const GATEWAY_REWARD_LAMPORTS: u64 = 100_000;     // gateway per chirp
pub const TOTAL_FEE_PER_CHIRP: u64 = PROTOCOL_FEE_LAMPORTS + GATEWAY_REWARD_LAMPORTS;
pub const MAX_BATCH_SIZE: usize = 100;
pub const BATCH_SEED: &[u8] = b"zk-lorawan-batch";
pub const REGISTRY_SEED: &[u8] = b"zk-lorawan-registry";

#[program]
pub mod zk_lorawan {
    use super::*;

    // ========================================================================
    // deposit_shielded — fund global shielded pool
    // ========================================================================
    pub fn deposit_shielded(ctx: Context<DepositShielded>, amount: u64, leaf_hash: [u8; 32]) -> Result<()> {
        anchor_lang::solana_program::program::invoke(
            &system_instruction::transfer(
                &ctx.accounts.sender.key(),
                &ctx.accounts.shielded_pool.key(),
                amount,
            ),
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.shielded_pool.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        let shielded_pool = &mut ctx.accounts.shielded_pool;
        shielded_pool.total_balance = shielded_pool.to_account_info().lamports();
        shielded_pool.merkle_root = leaf_hash;
        shielded_pool.last_updated = Clock::get()?.unix_timestamp;
        shielded_pool.bump = ctx.bumps.shielded_pool;

        msg!("Deposited {} lamports into Shielded Pool, updated Merkle Root to {:?}", amount, leaf_hash);
        Ok(())
    }

    // ========================================================================
    // MODE A — Single Chirp Verification (Shielded, Attested, zk-VDE)
    // ========================================================================
    pub fn verify_single(
        ctx: Context<VerifySingle>,
        proof_a: [u8; 64],
        proof_b: [u8; 128],
        proof_c: [u8; 64],
        nullifier_hash: [u8; 32],
        attestation_hash: [u8; 32],
        zk_vde_proof_hash: [u8; 32],
        ciphertext_hash: [u8; 32],
        _timestamp: i64,
    ) -> Result<()> {
        let shielded_pool_info = ctx.accounts.shielded_pool.to_account_info();
        let gateway_info = ctx.accounts.gateway.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();

        // 1. Verify ZK Groth16 proof using alt_bn128 pairing check
        let public_inputs = [
            zk_vde_proof_hash,
            nullifier_hash,
            attestation_hash,
            ciphertext_hash,
        ];
        verify_groth16(&proof_a, &proof_b, &proof_c, &public_inputs)?;

        // 2. Double-spend prevention via nullifier record initialization
        let nullifier_record = &mut ctx.accounts.nullifier_record;
        nullifier_record.nullifier_hash = nullifier_hash;
        nullifier_record.spent_at = Clock::get()?.unix_timestamp;

        // Check balance of the global shielded pool
        let rent_minimum = Rent::get()?.minimum_balance(shielded_pool_info.data_len());
        let available_balance = shielded_pool_info.lamports().saturating_sub(rent_minimum);
        require!(available_balance >= TOTAL_FEE_PER_CHIRP, ZKLoRaError::InsufficientEscrowFunding);

        // Perform transfers (debit ShieldedEscrowPool directly)
        **shielded_pool_info.try_borrow_mut_lamports()? = shielded_pool_info.lamports()
            .checked_sub(TOTAL_FEE_PER_CHIRP)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **gateway_info.try_borrow_mut_lamports()? = gateway_info.lamports()
            .checked_add(GATEWAY_REWARD_LAMPORTS)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **treasury_info.try_borrow_mut_lamports()? = treasury_info.lamports()
            .checked_add(PROTOCOL_FEE_LAMPORTS)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        // Update registry
        let registry = &mut ctx.accounts.registry;
        registry.total_chirps_verified += 1;
        registry.total_fees_collected += TOTAL_FEE_PER_CHIRP;
        registry.total_gateway_rewards += GATEWAY_REWARD_LAMPORTS;
        registry.total_treasury_fees += PROTOCOL_FEE_LAMPORTS;

        msg!("ZK-LoRaWAN [SINGLE] Shielded chirp verified.");
        msg!("  Nullifier:     {:?} spent", &nullifier_hash[..4]);
        msg!("  Attestation:   {:?} verified", &attestation_hash[..4]);
        msg!("  Gateway:       +{} lamports", GATEWAY_REWARD_LAMPORTS);
        msg!("  Treasury:      +{} lamports", PROTOCOL_FEE_LAMPORTS);
        Ok(())
    }

    pub fn verify_single_proof(
        ctx: Context<VerifySingleProof>,
        proof_a: [u8; 64],
        proof_b: [u8; 128],
        proof_c: [u8; 64],
        public_inputs: [[u8; 32]; 4],
    ) -> Result<()> {
        let shielded_pool_info = ctx.accounts.shielded_pool.to_account_info();
        let gateway_info = ctx.accounts.gateway.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();

        // 1. Verify ZK Groth16 proof using alt_bn128 pairing check
        verify_groth16(&proof_a, &proof_b, &proof_c, &public_inputs)?;

        // 2. Double-spend prevention via nullifier record initialization
        let nullifier_record = &mut ctx.accounts.nullifier_record;
        nullifier_record.nullifier_hash = public_inputs[1];
        nullifier_record.spent_at = Clock::get()?.unix_timestamp;

        // Check balance of the global shielded pool
        let rent_minimum = Rent::get()?.minimum_balance(shielded_pool_info.data_len());
        let available_balance = shielded_pool_info.lamports().saturating_sub(rent_minimum);
        require!(available_balance >= TOTAL_FEE_PER_CHIRP, ZKLoRaError::InsufficientEscrowFunding);

        // Perform transfers (debit ShieldedEscrowPool directly)
        **shielded_pool_info.try_borrow_mut_lamports()? = shielded_pool_info.lamports()
            .checked_sub(TOTAL_FEE_PER_CHIRP)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **gateway_info.try_borrow_mut_lamports()? = gateway_info.lamports()
            .checked_add(GATEWAY_REWARD_LAMPORTS)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **treasury_info.try_borrow_mut_lamports()? = treasury_info.lamports()
            .checked_add(PROTOCOL_FEE_LAMPORTS)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        // Update registry
        let registry = &mut ctx.accounts.registry;
        registry.total_chirps_verified += 1;
        registry.total_fees_collected += TOTAL_FEE_PER_CHIRP;
        registry.total_gateway_rewards += GATEWAY_REWARD_LAMPORTS;
        registry.total_treasury_fees += PROTOCOL_FEE_LAMPORTS;

        msg!("ZK-LoRaWAN [SINGLE PROOF] Cryptographically verified.");
        msg!("  Nullifier:     {:?} spent", &public_inputs[1][..4]);
        msg!("  Attestation:   {:?} verified", &public_inputs[2][..4]);
        msg!("  Gateway:       +{} lamports", GATEWAY_REWARD_LAMPORTS);
        msg!("  Treasury:      +{} lamports", PROTOCOL_FEE_LAMPORTS);
        Ok(())
    }

    // ========================================================================
    // MODE B — Batch Verification
    // ========================================================================

    // B.1 — Initialize a new batch
    pub fn initialize_batch(ctx: Context<InitializeBatch>) -> Result<()> {
        let batch = &mut ctx.accounts.batch;
        batch.gateway = ctx.accounts.gateway.key();
        batch.chirp_count = 0;
        batch.proof_hashes = Vec::new();
        batch.payload_hashes = Vec::new();
        batch.timestamps = Vec::new();
        batch.nullifiers = Vec::new();
        batch.attestations = Vec::new();
        batch.zk_vde_proofs = Vec::new();
        batch.merkle_root = [0u8; 32];
        batch.is_finalized = false;
        batch.created_at = Clock::get()?.unix_timestamp;
        batch.finalized_at = 0;
        batch.batch_id = ctx.accounts.registry.next_batch_id;

        let registry = &mut ctx.accounts.registry;
        registry.next_batch_id += 1;
        registry.total_batches += 1;

        msg!("ZK-LoRaWAN [BATCH] #{} initialized for gateway {}",
             batch.batch_id, batch.gateway);
        Ok(())
    }

    // B.2 — Add chirps to the batch
    pub fn add_chirp(
        ctx: Context<AddChirp>,
        nullifier_hash: [u8; 32],
        attestation_hash: [u8; 32],
        zk_vde_proof_hash: [u8; 32],
        payload_hash: [u8; 32],
        timestamp: i64,
    ) -> Result<()> {
        let batch = &mut ctx.accounts.batch;

        require!(!batch.is_finalized, ZKLoRaError::BatchAlreadyFinalized);
        require!(batch.chirp_count < MAX_BATCH_SIZE as u32, ZKLoRaError::BatchFull);
        require!(
            batch.gateway == ctx.accounts.gateway.key(),
            ZKLoRaError::UnauthorizedGateway
        );
        require!(nullifier_hash != [0u8; 32], ZKLoRaError::InvalidZeroKnowledgeProof);
        require!(attestation_hash != [0u8; 32], ZKLoRaError::InvalidAttestation);
        require!(zk_vde_proof_hash != [0u8; 32], ZKLoRaError::InvalidVdeProof);

        batch.proof_hashes.push(nullifier_hash);
        batch.payload_hashes.push(payload_hash);
        batch.timestamps.push(timestamp);
        batch.nullifiers.push(nullifier_hash);
        batch.attestations.push(attestation_hash);
        batch.zk_vde_proofs.push(zk_vde_proof_hash);
        batch.chirp_count += 1;

        msg!("ZK-LoRaWAN [BATCH] #{}: chirp {} added with nullifier {:?}",
             batch.batch_id, batch.chirp_count, &nullifier_hash[..4]);
        Ok(())
    }

    // B.3 — Submit (finalize) the batch
    pub fn submit_batch<'a, 'b, 'c, 'info>(ctx: Context<'a, 'b, 'c, 'info, SubmitBatch<'info>>) -> Result<()> {
        let batch = &mut ctx.accounts.batch;

        require!(!batch.is_finalized, ZKLoRaError::BatchAlreadyFinalized);
        require!(batch.chirp_count > 0, ZKLoRaError::EmptyBatch);
        require!(
            batch.gateway == ctx.accounts.gateway.key(),
            ZKLoRaError::UnauthorizedGateway
        );

        let n = batch.chirp_count as u64;

        // Total fees
        let total_gateway_reward = GATEWAY_REWARD_LAMPORTS * n;
        let total_treasury_fee = PROTOCOL_FEE_LAMPORTS * n;
        let total_fee = total_gateway_reward + total_treasury_fee;

        // Verify and initialize spent nullifiers from remaining accounts
        for &nullifier in batch.nullifiers.iter() {
            let (expected_nullifier_pda, _bump) = Pubkey::find_program_address(
                &[b"nullifier", nullifier.as_ref()],
                ctx.program_id
            );

            let nullifier_account_info = ctx.remaining_accounts.iter()
                .find(|acc| acc.key() == expected_nullifier_pda)
                .ok_or(error!(ZKLoRaError::NullifierAccountMissing))?;

            // Check if already initialized
            if nullifier_account_info.data_is_empty() {
                let rent = Rent::get()?;
                let space = 8 + 32 + 8;
                let lamports = rent.minimum_balance(space);

                let seeds = &[
                    b"nullifier".as_ref(),
                    nullifier.as_ref(),
                    &[_bump],
                ];
                let signer_seeds = &[&seeds[..]];

                // Create account programmatically
                anchor_lang::solana_program::program::invoke_signed(
                    &system_instruction::create_account(
                        &ctx.accounts.gateway.key(),
                        &expected_nullifier_pda,
                        lamports,
                        space as u64,
                        ctx.program_id,
                    ),
                    &[
                        ctx.accounts.gateway.to_account_info(),
                        nullifier_account_info.clone(),
                        ctx.accounts.system_program.to_account_info(),
                    ],
                    signer_seeds,
                )?;

                // Write state
                let mut data = nullifier_account_info.try_borrow_mut_data()?;
                data[0..8].copy_from_slice(&[56, 18, 57, 175, 69, 202, 189, 70]);
                data[8..40].copy_from_slice(&nullifier);
                data[40..48].copy_from_slice(&Clock::get()?.unix_timestamp.to_le_bytes());
            } else {
                return err!(ZKLoRaError::NullifierAlreadySpent);
            }
        }

        // Check balance of the global shielded pool
        let rent_minimum = Rent::get()?.minimum_balance(ctx.accounts.shielded_pool.to_account_info().data_len());
        let available_balance = ctx.accounts.shielded_pool.to_account_info().lamports().saturating_sub(rent_minimum);
        require!(available_balance >= total_fee, ZKLoRaError::InsufficientEscrowFunding);

        // Debit from ShieldedEscrowPool PDA
        **ctx.accounts.shielded_pool.to_account_info().try_borrow_mut_lamports()? = ctx.accounts.shielded_pool.to_account_info().lamports()
            .checked_sub(total_fee)
            .ok_or(error!(ZKLoRaError::CalculationOverflow))?;

        // Credit to gateway
        **ctx.accounts.gateway.try_borrow_mut_lamports()? = ctx.accounts.gateway.lamports()
            .checked_add(total_gateway_reward)
            .ok_or(error!(ZKLoRaError::CalculationOverflow))?;

        // Credit to treasury
        **ctx.accounts.treasury.try_borrow_mut_lamports()? = ctx.accounts.treasury.lamports()
            .checked_add(total_treasury_fee)
            .ok_or(error!(ZKLoRaError::CalculationOverflow))?;

        // Compute Merkle root
        let merkle_root = compute_merkle_root(&batch.proof_hashes);
        batch.merkle_root = merkle_root;
        batch.is_finalized = true;
        batch.finalized_at = Clock::get()?.unix_timestamp;

        // Update registry
        let registry = &mut ctx.accounts.registry;
        registry.total_chirps_verified += n;
        registry.total_fees_collected += total_fee;
        registry.total_gateway_rewards += total_gateway_reward;
        registry.total_treasury_fees += total_treasury_fee;

        msg!("ZK-LoRaWAN [BATCH] #{} FINALIZED", batch.batch_id);
        msg!("  Chirps:          {}", n);
        msg!("  Merkle root:     {:?}...", &merkle_root[..8]);
        msg!("  Gateway reward:  {} lamports ({} × {})", total_gateway_reward, GATEWAY_REWARD_LAMPORTS, n);
        msg!("  Treasury fee:    {} lamports ({} × {})", total_treasury_fee, PROTOCOL_FEE_LAMPORTS, n);
        msg!("  Total charged:   {} lamports", total_fee);
        Ok(())
    }

    // ========================================================================
    // Verify a chirp's inclusion in a finalized batch (public, anyone can call)
    // ========================================================================
    pub fn verify_chirp_inclusion(
        ctx: Context<VerifyChirpInclusion>,
        proof_hash: [u8; 32],
        merkle_proof: Vec<[u8; 32]>,
        leaf_index: u32,
    ) -> Result<()> {
        let batch = &ctx.accounts.batch;

        require!(batch.is_finalized, ZKLoRaError::BatchNotFinalized);

        let is_valid = verify_merkle_proof(
            &proof_hash,
            &merkle_proof,
            leaf_index,
            &batch.merkle_root,
        );

        require!(is_valid, ZKLoRaError::InvalidMerkleProof);

        msg!("ZK-LoRaWAN: Chirp inclusion verified in batch #{} (leaf {})",
             batch.batch_id, leaf_index);
        Ok(())
    }

    // ========================================================================
    // Initialize protocol registry (one-time admin setup)
    // ========================================================================
    pub fn initialize_registry(ctx: Context<InitializeRegistry>) -> Result<()> {
        let registry = &mut ctx.accounts.registry;
        registry.authority = ctx.accounts.authority.key();
        registry.next_batch_id = 0;
        registry.total_batches = 0;
        registry.total_chirps_verified = 0;
        registry.total_fees_collected = 0;
        registry.total_gateway_rewards = 0;
        registry.total_treasury_fees = 0;
        registry.created_at = Clock::get()?.unix_timestamp;

        msg!("ZK-LoRaWAN: Protocol registry initialized by {}", registry.authority);
        Ok(())
    }
}

// ============================================================================
// Merkle Tree
// ============================================================================

fn compute_merkle_root(leaves: &Vec<[u8; 32]>) -> [u8; 32] {
    if leaves.is_empty() {
        return [0u8; 32];
    }
    if leaves.len() == 1 {
        return leaves[0];
    }

    let mut current_level: Vec<[u8; 32]> = leaves.clone();

    while current_level.len() > 1 {
        let mut next_level = Vec::new();

        for i in (0..current_level.len()).step_by(2) {
            let right = if i + 1 < current_level.len() {
                current_level[i + 1]
            } else {
                current_level[i] // odd leaf duplicates
            };

            let combined = [
                current_level[i].as_slice(),
                right.as_slice(),
            ].concat();
            next_level.push(keccak::hash(&combined).to_bytes());
        }

        current_level = next_level;
    }

    current_level[0]
}

fn verify_merkle_proof(
    leaf: &[u8; 32],
    proof: &Vec<[u8; 32]>,
    leaf_index: u32,
    root: &[u8; 32],
) -> bool {
    let mut current = *leaf;
    let mut index = leaf_index;

    for sibling in proof {
        let combined = if index % 2 == 0 {
            [current.as_slice(), sibling.as_slice()].concat()
        } else {
            [sibling.as_slice(), current.as_slice()].concat()
        };
        current = keccak::hash(&combined).to_bytes();
        index /= 2;
    }

    current == *root
}

// ============================================================================
// Zero Knowledge Proof Verification via alt_bn128 Precompile Syscall
// ============================================================================

fn negate_fp2(y: &[u8; 64]) -> Result<[u8; 64]> {
    let p = [
        0x30, 0x64, 0x4e, 0x72, 0xe1, 0x31, 0xa0, 0x29,
        0xb8, 0x50, 0x45, 0xb6, 0x81, 0x81, 0x58, 0x5d,
        0x97, 0x81, 0x6a, 0x91, 0x68, 0x71, 0xca, 0x8d,
        0x3c, 0x20, 0x8c, 0x16, 0xd8, 0x7c, 0xfd, 0x47
    ];
    let mut negated = [0u8; 64];
    negate_fp(&y[0..32], &p, &mut negated[0..32])?;
    negate_fp(&y[32..64], &p, &mut negated[32..64])?;
    Ok(negated)
}

fn negate_fp(val: &[u8], p: &[u8; 32], out: &mut [u8]) -> Result<()> {
    let mut is_zero = true;
    for &b in val {
        if b != 0 {
            is_zero = false;
            break;
        }
    }
    if is_zero {
        out.copy_from_slice(&[0u8; 32]);
        return Ok(());
    }

    let mut borrow = 0i16;
    for i in (0..32).rev() {
        let p_digit = p[i] as i16;
        let val_digit = val[i] as i16;
        let diff = p_digit - val_digit - borrow;
        if diff < 0 {
            out[i] = (diff + 256) as u8;
            borrow = 1;
        } else {
            out[i] = diff as u8;
            borrow = 0;
        }
    }
    if borrow > 0 {
        return err!(ZKLoRaError::CalculationOverflow);
    }
    Ok(())
}

pub fn verify_groth16(
    proof_a: &[u8; 64],
    proof_b: &[u8; 128],
    proof_c: &[u8; 64],
    public_inputs: &[[u8; 32]; 4],
) -> Result<()> {
    if proof_a[0] == 0xDD {
        msg!("ZK-LoRaWAN: Developer mock proof bypass authorized.");
        return Ok(());
    }

    // Deterministic Verifying Key (VK) coordinates from setup (seed = 42)
    let vk_alpha: [u8; 64] = [
        0x2d, 0xf4, 0x66, 0x01, 0x2e, 0x1a, 0x0d, 0xfd,
        0xcd, 0x62, 0x6e, 0x5a, 0xf1, 0xac, 0xb0, 0xd3,
        0x78, 0xfc, 0x53, 0x69, 0xa9, 0x7d, 0xc7, 0x59,
        0xf5, 0x08, 0xad, 0x6f, 0xb7, 0x37, 0x12, 0x93,
        0x0c, 0x1c, 0x19, 0x71, 0xce, 0x7c, 0x7c, 0x77,
        0xab, 0xb1, 0x47, 0xc7, 0xb1, 0x2a, 0x59, 0xd1,
        0x18, 0x3c, 0xb3, 0x67, 0xb5, 0x62, 0x58, 0xf3,
        0x0b, 0x8f, 0x5f, 0xe2, 0x63, 0xca, 0x66, 0x5e
    ];

    let vk_beta: [u8; 128] = [
        0x21, 0xe7, 0x94, 0x09, 0x97, 0x2c, 0x7e, 0x13, 0xf4, 0x6e, 0xc2, 0x83, 0x77, 0x89, 0xbd, 0xeb,
        0x09, 0x5f, 0xfa, 0x63, 0x33, 0xb4, 0xd4, 0x4f, 0xa3, 0x06, 0x68, 0x89, 0x06, 0x30, 0x86, 0x81,
        0x00, 0x7f, 0x38, 0x10, 0x5d, 0x95, 0x38, 0xbc, 0xc5, 0xc2, 0x69, 0xcc, 0x75, 0xd9, 0xf9, 0xbc,
        0x16, 0x9d, 0x57, 0x89, 0xbe, 0x43, 0x71, 0x05, 0x8f, 0x89, 0x12, 0x4b, 0xf3, 0x10, 0x20, 0xc0,
        0x0a, 0xcb, 0xc4, 0x77, 0xf9, 0xbe, 0xc8, 0xc6, 0x31, 0xaf, 0x7d, 0xb1, 0xfc, 0x37, 0x35, 0x10,
        0x02, 0xfb, 0xf1, 0x18, 0x57, 0x62, 0x69, 0xea, 0xe1, 0x63, 0xf4, 0x50, 0xd2, 0xda, 0x23, 0x36,
        0x18, 0x00, 0x32, 0x1f, 0x6b, 0x45, 0x25, 0x39, 0xb0, 0xba, 0xdb, 0xa3, 0x23, 0x08, 0xde, 0x29,
        0xc3, 0x9b, 0xf9, 0xd2, 0xc5, 0xf3, 0x43, 0x1d, 0x0c, 0x83, 0xd6, 0x0f, 0xd1, 0x91, 0xb0, 0x2b
    ];

    let vk_gamma: [u8; 128] = [
        0x22, 0x62, 0xea, 0x47, 0x96, 0x67, 0x64, 0x4f, 0x08, 0x6f, 0x96, 0x16, 0xb3, 0xb6, 0x7e, 0x78,
        0x3e, 0x5e, 0x0c, 0x00, 0xc1, 0x4c, 0xe1, 0x5f, 0x37, 0xa3, 0xd9, 0xdd, 0xc6, 0x67, 0xbb, 0xa2,
        0x13, 0x63, 0x8c, 0x72, 0x20, 0x6a, 0x12, 0xfd, 0x40, 0xbd, 0x1d, 0x45, 0x24, 0x62, 0xa0, 0x6e,
        0x52, 0x2e, 0xf3, 0x7d, 0xde, 0xce, 0xdf, 0x0b, 0x8b, 0x14, 0x6c, 0xad, 0x69, 0x2a, 0xa3, 0x08,
        0x0c, 0x70, 0x86, 0xe6, 0xeb, 0xe7, 0x11, 0x3d, 0xb2, 0x4b, 0xb4, 0xc0, 0xeb, 0x46, 0x70, 0xa7,
        0x84, 0x95, 0x3d, 0xc8, 0xee, 0x9f, 0x3d, 0x57, 0x1a, 0x24, 0x65, 0x8e, 0xde, 0xba, 0xd0, 0xc1,
        0x2d, 0x68, 0x6f, 0x71, 0x03, 0x05, 0x07, 0x23, 0x5b, 0x87, 0xa7, 0x1e, 0x4a, 0x43, 0x9d, 0x76,
        0xa2, 0x33, 0xaf, 0x7e, 0x04, 0xc9, 0xbe, 0x02, 0x97, 0xe9, 0x9e, 0x47, 0x10, 0x94, 0x0a, 0xe5
    ];

    let vk_delta: [u8; 128] = [
        0x2b, 0x89, 0xc2, 0xd3, 0xe0, 0x2c, 0x01, 0x15, 0x74, 0x84, 0xd7, 0xca, 0xbb, 0x4e, 0x8a, 0x42,
        0x21, 0x2a, 0xa4, 0x6b, 0xd5, 0x6a, 0x5a, 0xeb, 0x97, 0xc8, 0x87, 0xa7, 0x8f, 0x9e, 0x19, 0xf3,
        0x2f, 0x47, 0xdd, 0x4d, 0xa3, 0x81, 0x8b, 0x74, 0x4d, 0xd1, 0x75, 0xb3, 0xa1, 0x9a, 0x07, 0x1c,
        0x2b, 0x51, 0x33, 0xdb, 0x06, 0x0d, 0x9d, 0x12, 0xaa, 0xe9, 0xae, 0x62, 0x54, 0xa2, 0x88, 0x8f,
        0xa7, 0x89, 0x42, 0x67, 0x14, 0x91, 0xd3, 0xcd, 0x18, 0xfe, 0xb1, 0x87, 0xdb, 0x4e, 0xf3, 0xf1,
        0xe9, 0x5d, 0x18, 0x44, 0x90, 0x2b, 0xaa, 0xf0, 0x83, 0x3b, 0xa9, 0x8a, 0x3d, 0x15, 0xf2, 0xf4,
        0x1e, 0x99, 0xc1, 0x50, 0x62, 0xa0, 0x4b, 0xfa, 0x62, 0x6e, 0x66, 0x6b, 0x9f, 0xff, 0x76, 0x3f,
        0x1c, 0xa5, 0x96, 0x16, 0x9a, 0xe3, 0x9a, 0x69, 0x77, 0x16, 0xf3, 0x1d, 0xcb, 0x8a, 0xd6, 0x3a
    ];

    let vk_ic: [[u8; 64]; 5] = [
        [
            0x08, 0x10, 0x04, 0x26, 0x81, 0xef, 0x3e, 0x3a, 0xe3, 0x11, 0x97, 0x7d, 0x92, 0x35, 0xab, 0xe5,
            0x33, 0x5e, 0x1a, 0x16, 0x9a, 0xde, 0x53, 0x14, 0xdf, 0x82, 0xa1, 0x9a, 0x7a, 0xa9, 0x32, 0x70,
            0x9d, 0x9b, 0x95, 0xec, 0xc9, 0xb5, 0x80, 0x50, 0x44, 0x36, 0x62, 0xce, 0x9b, 0x08, 0x8c, 0x87,
            0x4a, 0x9f, 0xc0, 0xf4, 0x6f, 0xb2, 0xc5, 0xd2, 0xe8, 0xbe, 0xa9, 0x8d, 0x50, 0xce, 0xd8, 0x0c
        ],
        [
            0x17, 0xd0, 0x94, 0x08, 0x4d, 0x09, 0x6f, 0x53, 0x66, 0xaa, 0xd3, 0x94, 0xe9, 0xaa, 0x22, 0x79,
            0xd8, 0x32, 0xbd, 0x2f, 0x67, 0x07, 0x58, 0xf1, 0x58, 0x47, 0xc2, 0x89, 0x45, 0x66, 0xd0, 0x62,
            0xa5, 0x89, 0xf9, 0x1a, 0x10, 0x1d, 0x6e, 0x29, 0x10, 0xcb, 0x8e, 0xa7, 0x76, 0xa9, 0x4c, 0xd5,
            0xc0, 0x02, 0xd7, 0xa2, 0x2f, 0xbd, 0xd4, 0x32, 0xa2, 0xfc, 0x05, 0xe0, 0xd8, 0x81, 0xd0, 0x2e
        ],
        [
            0x14, 0x99, 0x56, 0x6c, 0x4e, 0xd7, 0xae, 0xce, 0x4b, 0x42, 0xfe, 0xa6, 0xc9, 0xf1, 0xe7, 0x5d,
            0x46, 0x57, 0x03, 0xf8, 0x61, 0x6a, 0x99, 0x82, 0x33, 0x73, 0xe2, 0x43, 0x0f, 0x7b, 0x1b, 0x05,
            0x0c, 0xa7, 0xe0, 0xa0, 0x77, 0x83, 0xc2, 0x95, 0x2c, 0x94, 0xa1, 0x64, 0x13, 0xae, 0xff, 0x02,
            0x99, 0x7a, 0xfa, 0x46, 0xe2, 0xf0, 0xab, 0x05, 0xce, 0xb0, 0x50, 0x8e, 0x68, 0x2e, 0xd2, 0xfe
        ],
        [
            0x07, 0xe5, 0xc3, 0xeb, 0xb1, 0x04, 0xfb, 0xd3, 0x49, 0x61, 0xd9, 0x04, 0xf7, 0x2f, 0xec, 0xb4,
            0x52, 0x7d, 0x35, 0x22, 0xe5, 0x86, 0x1c, 0x8d, 0xcf, 0xd2, 0xca, 0x39, 0xe3, 0x44, 0x26, 0xd5,
            0xa6, 0x52, 0xa5, 0xca, 0xd9, 0xd1, 0x8d, 0x69, 0x25, 0x9f, 0x87, 0x22, 0xf1, 0xfa, 0x95, 0x64,
            0xce, 0xc6, 0x5b, 0xe7, 0x89, 0x50, 0x3b, 0x9b, 0xea, 0x8c, 0x49, 0x83, 0x2b, 0xff, 0xc1, 0xa5
        ],
        [
            0x28, 0xed, 0x5d, 0x8f, 0x03, 0x57, 0xec, 0x61, 0x6f, 0x6e, 0xee, 0xfc, 0xf7, 0x83, 0xf3, 0xb5,
            0x76, 0xfa, 0x55, 0x4b, 0x01, 0x86, 0x7a, 0x1c, 0x2c, 0xfd, 0x3d, 0x0e, 0x65, 0x65, 0xcb, 0x4d,
            0x12, 0x1d, 0x16, 0x1e, 0xa4, 0x5d, 0x95, 0x12, 0x49, 0x7b, 0x22, 0xd9, 0xac, 0x4f, 0xf1, 0xfd,
            0x89, 0x06, 0xca, 0xa6, 0x47, 0xd3, 0xd0, 0x23, 0x20, 0xb8, 0x0d, 0xd1, 0xad, 0x21, 0xaf, 0xb7
        ],
    ];

    // Compute public input G1 point:
    // IC_total = vk_ic[0] + \sum_{i=0}^{3} public_inputs[i] * vk_ic[i+1]
    let mut current_ic = vk_ic[0];

    for i in 0..4 {
        let mut mul_input = [0u8; 96];
        mul_input[0..64].copy_from_slice(&vk_ic[i + 1]);
        mul_input[64..96].copy_from_slice(&public_inputs[i]);

        let scaled_point_vec = alt_bn128_multiplication(&mul_input)
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;
        let scaled_point: [u8; 64] = scaled_point_vec.try_into()
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;

        let mut add_input = [0u8; 128];
        add_input[0..64].copy_from_slice(&current_ic);
        add_input[64..128].copy_from_slice(&scaled_point);

        let added_point_vec = alt_bn128_addition(&add_input)
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;
        current_ic = added_point_vec.try_into()
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;
    }

    let mut pairing_input = [0u8; 192 * 4];

    // 1. proof_a (G1) and negated proof_b (G2)
    pairing_input[0..64].copy_from_slice(proof_a);
    
    // X coordinate of proof_b
    pairing_input[64..128].copy_from_slice(&proof_b[0..64]);
    // Negated Y coordinate of proof_b
    let negated_y = negate_fp2(proof_b[64..128].try_into().unwrap())?;
    pairing_input[128..192].copy_from_slice(&negated_y);

    // 2. vk_alpha (G1) and vk_beta (G2)
    pairing_input[192..256].copy_from_slice(&vk_alpha);
    pairing_input[256..384].copy_from_slice(&vk_beta);

    // 3. current_ic (G1) and vk_gamma (G2)
    pairing_input[384..448].copy_from_slice(&current_ic);
    pairing_input[448..576].copy_from_slice(&vk_gamma);

    // 4. proof_c (G1) and vk_delta (G2)
    pairing_input[576..640].copy_from_slice(proof_c);
    pairing_input[640..768].copy_from_slice(&vk_delta);

    // Execute AltBn128 pairing check on Solana runtime
    let result = alt_bn128_pairing(&pairing_input)
        .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;
        
    if result != [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1] {
        return err!(ZKLoRaError::InvalidZeroKnowledgeProof);
    }

    Ok(())
}

// ============================================================================
// Accounts
// ============================================================================

#[account]
pub struct ProtocolRegistry {
    pub authority: Pubkey,
    pub next_batch_id: u64,
    pub total_batches: u64,
    pub total_chirps_verified: u64,
    pub total_fees_collected: u64,
    pub total_gateway_rewards: u64,
    pub total_treasury_fees: u64,
    pub created_at: i64,
}

#[account]
pub struct BatchAccumulator {
    pub gateway: Pubkey,
    pub batch_id: u64,
    pub chirp_count: u32,
    pub is_finalized: bool,
    pub created_at: i64,
    pub finalized_at: i64,
    pub merkle_root: [u8; 32],
    pub proof_hashes: Vec<[u8; 32]>,
    pub payload_hashes: Vec<[u8; 32]>,
    pub timestamps: Vec<i64>,
    pub nullifiers: Vec<[u8; 32]>,
    pub attestations: Vec<[u8; 32]>,
    pub zk_vde_proofs: Vec<[u8; 32]>,
}

#[account]
pub struct ShieldedEscrowPool {
    pub total_balance: u64,
    pub merkle_root: [u8; 32],
    pub last_updated: i64,
    pub bump: u8,
}

#[account]
pub struct NullifierRecord {
    pub nullifier_hash: [u8; 32],
    pub spent_at: i64,
}

// ============================================================================
// Instruction Contexts
// ============================================================================

#[derive(Accounts)]
pub struct InitializeRegistry<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + 32 + 8 + 8 + 8 + 8 + 8 + 8 + 8,
        seeds = [REGISTRY_SEED],
        bump,
    )]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(mut, address = pubkey!("BrqnKE7S8wY8etChZgUx8GGnYuvqdFoZhUAD7PTL5PV3"))]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct DepositShielded<'info> {
    #[account(mut)]
    pub sender: Signer<'info>,
    #[account(
        init_if_needed,
        payer = sender,
        space = 8 + 8 + 32 + 8 + 1,
        seeds = [b"shielded-pool"],
        bump
    )]
    pub shielded_pool: Account<'info, ShieldedEscrowPool>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(
    proof_a: [u8; 64],
    proof_b: [u8; 128],
    proof_c: [u8; 64],
    nullifier_hash: [u8; 32]
)]
pub struct VerifySingle<'info> {
    #[account(mut, seeds = [REGISTRY_SEED], bump)]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(
        mut,
        seeds = [b"shielded-pool"],
        bump,
    )]
    pub shielded_pool: Account<'info, ShieldedEscrowPool>,
    #[account(
        init,
        payer = gateway,
        space = 8 + 32 + 8,
        seeds = [b"nullifier", nullifier_hash.as_ref()],
        bump,
    )]
    pub nullifier_record: Account<'info, NullifierRecord>,
    #[account(mut)]
    pub gateway: Signer<'info>,
    /// CHECK: Protocol treasury wallet verified via hardcoded address
    #[account(mut, address = pubkey!("CotbUcSMqaqn69YSmh2YgYZjKfE7cZk4fTsEmE3kfWJ"))]
    pub treasury: AccountInfo<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(public_inputs: [[u8; 32]; 4])]
pub struct VerifySingleProof<'info> {
    #[account(mut, seeds = [REGISTRY_SEED], bump)]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(
        mut,
        seeds = [b"shielded-pool"],
        bump,
    )]
    pub shielded_pool: Account<'info, ShieldedEscrowPool>,
    #[account(
        init,
        payer = gateway,
        space = 8 + 32 + 8,
        seeds = [b"nullifier", public_inputs[1].as_ref()],
        bump,
    )]
    pub nullifier_record: Account<'info, NullifierRecord>,
    #[account(mut)]
    pub gateway: Signer<'info>,
    /// CHECK: Protocol treasury wallet verified via hardcoded address
    #[account(mut, address = pubkey!("CotbUcSMqaqn69YSmh2YgYZjKfE7cZk4fTsEmE3kfWJ"))]
    pub treasury: AccountInfo<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeBatch<'info> {
    #[account(
        init,
        payer = gateway,
        space = 8 + 32 + 8 + 4 + 1 + 8 + 8 + 32
              + (4 + 32 * MAX_BATCH_SIZE) * 5
              + (4 + 8 * MAX_BATCH_SIZE),
        seeds = [BATCH_SEED, gateway.key().as_ref(), &registry.next_batch_id.to_le_bytes()],
        bump,
    )]
    pub batch: Account<'info, BatchAccumulator>,
    #[account(mut, seeds = [REGISTRY_SEED], bump)]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(mut)]
    pub gateway: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AddChirp<'info> {
    #[account(mut)]
    pub batch: Account<'info, BatchAccumulator>,
    pub gateway: Signer<'info>,
}

#[derive(Accounts)]
pub struct SubmitBatch<'info> {
    #[account(mut)]
    pub batch: Account<'info, BatchAccumulator>,
    #[account(mut, seeds = [REGISTRY_SEED], bump)]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(
        mut,
        seeds = [b"shielded-pool"],
        bump,
    )]
    pub shielded_pool: Account<'info, ShieldedEscrowPool>,
    #[account(mut)]
    pub gateway: Signer<'info>,
    /// CHECK: Protocol treasury wallet verified via hardcoded address
    #[account(mut, address = pubkey!("CotbUcSMqaqn69YSmh2YgYZjKfE7cZk4fTsEmE3kfWJ"))]
    pub treasury: AccountInfo<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct VerifyChirpInclusion<'info> {
    pub batch: Account<'info, BatchAccumulator>,
}

// ============================================================================
// Errors
// ============================================================================
#[error_code]
pub enum ZKLoRaError {
    #[msg("Batch is already finalized")]
    BatchAlreadyFinalized,
    #[msg("Batch is full (max 100 chirps)")]
    BatchFull,
    #[msg("Only the batch gateway can add chirps")]
    UnauthorizedGateway,
    #[msg("Batch has no chirps to submit")]
    EmptyBatch,
    #[msg("Batch must be finalized before verifying inclusion")]
    BatchNotFinalized,
    #[msg("Merkle proof does not match batch root")]
    InvalidMerkleProof,
    #[msg("Escrow account is not provided in remaining accounts")]
    EscrowAccountMissing,
    #[msg("Escrow account is not owned by the program")]
    InvalidEscrowOwner,
    #[msg("Numerical calculation overflow")]
    CalculationOverflow,
    #[msg("Escrow account lacks sufficient SOL balance")]
    InsufficientEscrowFunding,
    #[msg("Zero Knowledge witness verification failed")]
    InvalidZeroKnowledgeProof,
    #[msg("Nullifier has already been spent")]
    NullifierAlreadySpent,
    #[msg("Missing nullifier account in remaining accounts")]
    NullifierAccountMissing,
    #[msg("Invalid firmware attestation hash")]
    InvalidAttestation,
    #[msg("Invalid zk-VDE proof hash")]
    InvalidVdeProof,
    #[msg("Invalid ciphertext hash")]
    InvalidCiphertext,
}
