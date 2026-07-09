// Watermark: ip zymatica.space | astronautshe.com
// Copyright (c) 2026 Zymatica / TheAiCollective.art. Licensed under Apache 2.0.
//
// ZK-LoRaWAN Solana Anchor Program — Dual Mode (Single + Batch)
// Upgraded to Advanced Shielded Pool (ZK-Compression), Micro-TEE Attestation & zk-VDE
// ==============================================================================

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{alt_bn128::prelude::*, keccak, pubkey, system_instruction};

#[cfg(feature = "integration-test")]
declare_id!("7wDzutwwr37nfxeMRydy5UEyREKho3Vjm8SxJgR4fzFy");
#[cfg(not(feature = "integration-test"))]
declare_id!("4HRP2eV8qtYW54ozQmnGDjF7emwb8MvqFcF89UgSM6iC");

// ============================================================================
// Protocol Constants
// ============================================================================
pub const PROTOCOL_FEE_LAMPORTS: u64 = 50_000; // treasury per chirp
pub const GATEWAY_REWARD_LAMPORTS: u64 = 100_000; // gateway per chirp
pub const TOTAL_FEE_PER_CHIRP: u64 = PROTOCOL_FEE_LAMPORTS + GATEWAY_REWARD_LAMPORTS;
pub const MAX_BATCH_SIZE: usize = 100;
pub const BATCH_SEED: &[u8] = b"zk-lorawan-batch";
pub const REGISTRY_SEED: &[u8] = b"zk-lorawan-registry";
#[cfg(feature = "integration-test")]
pub const ADMIN_AUTHORITY: Pubkey = pubkey!("FXdqcsZZnirF1sLYm4huXZeFTLwsqJ3ueNZJdPWUMkRc");
#[cfg(not(feature = "integration-test"))]
pub const ADMIN_AUTHORITY: Pubkey = pubkey!("BrqnKE7S8wY8etChZgUx8GGnYuvqdFoZhUAD7PTL5PV3");

#[program]
pub mod zk_lorawan {
    use super::*;

    // ========================================================================
    // deposit_shielded — fund global shielded pool
    // ========================================================================
    pub fn deposit_shielded(
        ctx: Context<DepositShielded>,
        amount: u64,
        leaf_hash: [u8; 32],
    ) -> Result<()> {
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

        msg!(
            "Deposited {} lamports into Shielded Pool, updated Merkle Root to {:?}",
            amount,
            leaf_hash
        );
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
        deposit_commitment: [u8; 32],
        firmware_hash: [u8; 32],
        _timestamp: i64,
        merkle_proof: Vec<[u8; 32]>,
        leaf_index: u32,
    ) -> Result<()> {
        let shielded_pool_info = ctx.accounts.shielded_pool.to_account_info();
        let gateway_info = ctx.accounts.gateway.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();

        // 0. Verify Merkle membership proof in the shielded pool
        let is_member = verify_merkle_proof(
            &zk_vde_proof_hash,
            &merkle_proof,
            leaf_index,
            &ctx.accounts.shielded_pool.merkle_root,
        );
        require!(is_member, ZKLoRaError::InvalidMerkleProof);

        // 1. Verify ZK Groth16 proof using alt_bn128 pairing check (with gateway address binding)
        let gateway_key = ctx.accounts.gateway.key().to_bytes();
        let mut gateway_part1 = [0u8; 32];
        gateway_part1[16..32].copy_from_slice(&gateway_key[0..16]);
        let mut gateway_part2 = [0u8; 32];
        gateway_part2[16..32].copy_from_slice(&gateway_key[16..32]);

        let public_inputs = [
            zk_vde_proof_hash,
            nullifier_hash,
            attestation_hash,
            ciphertext_hash,
            gateway_part1,
            gateway_part2,
            deposit_commitment,
            firmware_hash,
        ];
        verify_groth16(&proof_a, &proof_b, &proof_c, &public_inputs)?;

        // 2. Double-spend prevention via nullifier record initialization
        let nullifier_record = &mut ctx.accounts.nullifier_record;
        nullifier_record.nullifier_hash = nullifier_hash;
        nullifier_record.spent_at = Clock::get()?.unix_timestamp;

        // Check balance of the global shielded pool
        let rent_minimum = Rent::get()?.minimum_balance(shielded_pool_info.data_len());
        let available_balance = shielded_pool_info.lamports().saturating_sub(rent_minimum);
        require!(
            available_balance >= TOTAL_FEE_PER_CHIRP,
            ZKLoRaError::InsufficientEscrowFunding
        );

        // Perform transfers (debit ShieldedEscrowPool directly)
        **shielded_pool_info.try_borrow_mut_lamports()? = shielded_pool_info
            .lamports()
            .checked_sub(TOTAL_FEE_PER_CHIRP)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **gateway_info.try_borrow_mut_lamports()? = gateway_info
            .lamports()
            .checked_add(GATEWAY_REWARD_LAMPORTS)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **treasury_info.try_borrow_mut_lamports()? = treasury_info
            .lamports()
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
        public_inputs: [[u8; 32]; 8],
        merkle_proof: Vec<[u8; 32]>,
        leaf_index: u32,
    ) -> Result<()> {
        let shielded_pool_info = ctx.accounts.shielded_pool.to_account_info();
        let gateway_info = ctx.accounts.gateway.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();

        // 0. Verify Merkle membership proof in the shielded pool
        let is_member = verify_merkle_proof(
            &public_inputs[0],
            &merkle_proof,
            leaf_index,
            &ctx.accounts.shielded_pool.merkle_root,
        );
        require!(is_member, ZKLoRaError::InvalidMerkleProof);

        // 1. Verify ZK Groth16 proof using alt_bn128 pairing check
        verify_groth16(&proof_a, &proof_b, &proof_c, &public_inputs)?;

        // 2. Double-spend prevention via nullifier record initialization
        let nullifier_record = &mut ctx.accounts.nullifier_record;
        nullifier_record.nullifier_hash = public_inputs[1];
        nullifier_record.spent_at = Clock::get()?.unix_timestamp;

        // Check balance of the global shielded pool
        let rent_minimum = Rent::get()?.minimum_balance(shielded_pool_info.data_len());
        let available_balance = shielded_pool_info.lamports().saturating_sub(rent_minimum);
        require!(
            available_balance >= TOTAL_FEE_PER_CHIRP,
            ZKLoRaError::InsufficientEscrowFunding
        );

        // Perform transfers (debit ShieldedEscrowPool directly)
        **shielded_pool_info.try_borrow_mut_lamports()? = shielded_pool_info
            .lamports()
            .checked_sub(TOTAL_FEE_PER_CHIRP)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **gateway_info.try_borrow_mut_lamports()? = gateway_info
            .lamports()
            .checked_add(GATEWAY_REWARD_LAMPORTS)
            .ok_or(ZKLoRaError::CalculationOverflow)?;

        **treasury_info.try_borrow_mut_lamports()? = treasury_info
            .lamports()
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
        batch.nullifiers = Vec::new();
        batch.merkle_root = [0u8; 32];
        batch.is_finalized = false;
        batch.created_at = Clock::get()?.unix_timestamp;
        batch.finalized_at = 0;
        batch.batch_id = ctx.accounts.registry.next_batch_id;

        let registry = &mut ctx.accounts.registry;
        registry.next_batch_id += 1;
        registry.total_batches += 1;

        msg!(
            "ZK-LoRaWAN [BATCH] #{} initialized for gateway {}",
            batch.batch_id,
            batch.gateway
        );
        Ok(())
    }

    // B.2 — Add chirps to the batch
    pub fn add_chirp(
        ctx: Context<AddChirp>,
        proof_a: [u8; 64],
        proof_b: [u8; 128],
        proof_c: [u8; 64],
        nullifier_hash: [u8; 32],
        attestation_hash: [u8; 32],
        zk_vde_proof_hash: [u8; 32],
        payload_hash: [u8; 32],
        deposit_commitment: [u8; 32],
        firmware_hash: [u8; 32],
        _timestamp: i64,
        merkle_proof: Vec<[u8; 32]>,
        leaf_index: u32,
    ) -> Result<()> {
        let batch = &mut ctx.accounts.batch;

        require!(!batch.is_finalized, ZKLoRaError::BatchAlreadyFinalized);
        require!(
            batch.chirp_count < MAX_BATCH_SIZE as u32,
            ZKLoRaError::BatchFull
        );
        require!(
            batch.gateway == ctx.accounts.gateway.key(),
            ZKLoRaError::UnauthorizedGateway
        );

        // 0. Verify Merkle membership proof in the shielded pool
        let is_member = verify_merkle_proof(
            &zk_vde_proof_hash,
            &merkle_proof,
            leaf_index,
            &ctx.accounts.shielded_pool.merkle_root,
        );
        require!(is_member, ZKLoRaError::InvalidMerkleProof);

        // 1. Verify Groth16 proof per chirp inside the batch on-chain (with gateway address binding)
        let gateway_key = ctx.accounts.gateway.key().to_bytes();
        let mut gateway_part1 = [0u8; 32];
        gateway_part1[16..32].copy_from_slice(&gateway_key[0..16]);
        let mut gateway_part2 = [0u8; 32];
        gateway_part2[16..32].copy_from_slice(&gateway_key[16..32]);

        let public_inputs = [
            zk_vde_proof_hash,
            nullifier_hash,
            attestation_hash,
            payload_hash,
            gateway_part1,
            gateway_part2,
            deposit_commitment,
            firmware_hash,
        ];
        verify_groth16(&proof_a, &proof_b, &proof_c, &public_inputs)?;

        batch.nullifiers.push(nullifier_hash);
        batch.chirp_count += 1;

        msg!(
            "ZK-LoRaWAN [BATCH] #{}: chirp {} added with nullifier {:?}",
            batch.batch_id,
            batch.chirp_count,
            &nullifier_hash[..4]
        );
        Ok(())
    }

    // B.3 — Submit (finalize) the batch
    pub fn submit_batch<'a, 'b, 'c, 'info>(
        ctx: Context<'a, 'b, 'c, 'info, SubmitBatch<'info>>,
    ) -> Result<()> {
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
            let (expected_nullifier_pda, _bump) =
                Pubkey::find_program_address(&[b"nullifier", nullifier.as_ref()], ctx.program_id);

            let nullifier_account_info = ctx
                .remaining_accounts
                .iter()
                .find(|acc| acc.key() == expected_nullifier_pda)
                .ok_or(error!(ZKLoRaError::NullifierAccountMissing))?;

            // Check if already initialized
            if nullifier_account_info.data_is_empty() {
                let rent = Rent::get()?;
                let space = 8 + 32 + 8;
                let lamports = rent.minimum_balance(space);

                let seeds = &[b"nullifier".as_ref(), nullifier.as_ref(), &[_bump]];
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
        let rent_minimum =
            Rent::get()?.minimum_balance(ctx.accounts.shielded_pool.to_account_info().data_len());
        let available_balance = ctx
            .accounts
            .shielded_pool
            .to_account_info()
            .lamports()
            .saturating_sub(rent_minimum);
        require!(
            available_balance >= total_fee,
            ZKLoRaError::InsufficientEscrowFunding
        );

        // Debit from ShieldedEscrowPool PDA
        **ctx
            .accounts
            .shielded_pool
            .to_account_info()
            .try_borrow_mut_lamports()? = ctx
            .accounts
            .shielded_pool
            .to_account_info()
            .lamports()
            .checked_sub(total_fee)
            .ok_or(error!(ZKLoRaError::CalculationOverflow))?;

        // Credit to gateway
        **ctx.accounts.gateway.try_borrow_mut_lamports()? = ctx
            .accounts
            .gateway
            .lamports()
            .checked_add(total_gateway_reward)
            .ok_or(error!(ZKLoRaError::CalculationOverflow))?;

        // Credit to treasury
        **ctx.accounts.treasury.try_borrow_mut_lamports()? = ctx
            .accounts
            .treasury
            .lamports()
            .checked_add(total_treasury_fee)
            .ok_or(error!(ZKLoRaError::CalculationOverflow))?;

        // Compute Merkle root
        let merkle_root = compute_merkle_root(&batch.nullifiers);
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
        msg!(
            "  Gateway reward:  {} lamports ({} × {})",
            total_gateway_reward,
            GATEWAY_REWARD_LAMPORTS,
            n
        );
        msg!(
            "  Treasury fee:    {} lamports ({} × {})",
            total_treasury_fee,
            PROTOCOL_FEE_LAMPORTS,
            n
        );
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

        let is_valid =
            verify_merkle_proof(&proof_hash, &merkle_proof, leaf_index, &batch.merkle_root);

        require!(is_valid, ZKLoRaError::InvalidMerkleProof);

        msg!(
            "ZK-LoRaWAN: Chirp inclusion verified in batch #{} (leaf {})",
            batch.batch_id,
            leaf_index
        );
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

        msg!(
            "ZK-LoRaWAN: Protocol registry initialized by {}",
            registry.authority
        );
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

            let combined = [current_level[i].as_slice(), right.as_slice()].concat();
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
        0x30, 0x64, 0x4e, 0x72, 0xe1, 0x31, 0xa0, 0x29, 0xb8, 0x50, 0x45, 0xb6, 0x81, 0x81, 0x58,
        0x5d, 0x97, 0x81, 0x6a, 0x91, 0x68, 0x71, 0xca, 0x8d, 0x3c, 0x20, 0x8c, 0x16, 0xd8, 0x7c,
        0xfd, 0x47,
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
    public_inputs: &[[u8; 32]; 8],
) -> Result<()> {
    #[cfg(feature = "mock-verifier")]
    {
        if proof_a[0] == 0xDD {
            msg!("ZK-LoRaWAN: Developer mock proof bypass authorized via cargo feature.");
            return Ok(());
        }
    }

    // Verifying Key (VK) coordinates from OsRng-based trusted setup (8 public inputs)
    let vk_alpha: [u8; 64] = [
        0x02, 0x10, 0xa3, 0xc5, 0x10, 0x6f, 0x6c, 0xbd, 0x99, 0xf0, 0xbe, 0x7a, 0xb8, 0x8c, 0x05,
        0x2c, 0xa2, 0xb0, 0xcb, 0x24, 0xf4, 0xd8, 0x3e, 0x67, 0xde, 0xee, 0xca, 0x3d, 0x12, 0x90,
        0x61, 0x46, 0x03, 0x6b, 0x52, 0x87, 0x95, 0xc5, 0x77, 0x75, 0x1e, 0x81, 0x08, 0xaa, 0xeb,
        0x8c, 0xab, 0x76, 0x98, 0x5a, 0x5f, 0xce, 0x82, 0xc4, 0xce, 0x90, 0xca, 0x7b, 0x20, 0x7e,
        0x3b, 0x8a, 0x49, 0x6c,
    ];

    let vk_beta: [u8; 128] = [
        0x23, 0x0d, 0xc1, 0x38, 0x72, 0x87, 0xcc, 0x6e, 0x22, 0x34, 0x12, 0x34, 0x2f, 0x29, 0xdf,
        0xb6, 0x06, 0x9b, 0x2c, 0x24, 0x38, 0xf2, 0x8f, 0x66, 0xc2, 0x6b, 0x09, 0xbd, 0x78, 0xf2,
        0xcf, 0x83, 0x1b, 0xeb, 0x30, 0x15, 0xcb, 0x7f, 0x71, 0x56, 0x0e, 0x1e, 0xd6, 0x8a, 0x19,
        0x76, 0x45, 0x89, 0xe1, 0xa6, 0xc1, 0x91, 0xd8, 0x59, 0xa5, 0xcb, 0x00, 0xcc, 0x4e, 0x56,
        0xc8, 0x23, 0x5c, 0xc3, 0x28, 0x17, 0x02, 0x21, 0x55, 0x5e, 0x72, 0x6f, 0x88, 0xc3, 0x93,
        0x99, 0x2d, 0x9b, 0x11, 0xcb, 0x26, 0x12, 0x91, 0xb2, 0x48, 0x83, 0x74, 0x22, 0x1f, 0xd6,
        0x7b, 0x1f, 0xf7, 0x80, 0x82, 0xcf, 0x16, 0x48, 0xbe, 0x55, 0xd8, 0x79, 0x86, 0xd5, 0x20,
        0x44, 0x9d, 0xb6, 0x4c, 0xa1, 0xcf, 0x42, 0x59, 0xcd, 0xd5, 0x0b, 0xd4, 0x23, 0x7a, 0xd6,
        0x2a, 0x2c, 0x4d, 0x08, 0x98, 0xe7, 0x8d, 0x01,
    ];

    let vk_gamma: [u8; 128] = [
        0x0b, 0x57, 0x91, 0xae, 0xb4, 0x3b, 0x7b, 0x58, 0xba, 0xca, 0x9a, 0x2c, 0xdb, 0x60, 0x7b,
        0xa4, 0x1d, 0x25, 0xa1, 0x59, 0x4d, 0xc8, 0x5c, 0xaf, 0x1f, 0xfe, 0xab, 0x34, 0x10, 0x75,
        0xd1, 0x98, 0x28, 0x6a, 0x8e, 0xd0, 0x7f, 0x75, 0x16, 0xcd, 0x16, 0x61, 0x92, 0xa8, 0xb4,
        0x39, 0x74, 0x01, 0xd3, 0x45, 0xdf, 0x3e, 0x6a, 0x54, 0x6c, 0xdd, 0xbb, 0x4a, 0x0e, 0x6e,
        0x7c, 0xee, 0x32, 0xaa, 0x10, 0xa3, 0x29, 0x88, 0xab, 0xcf, 0x90, 0x88, 0xb0, 0x2b, 0x20,
        0xd1, 0x5b, 0x20, 0x98, 0xf5, 0xc5, 0x1b, 0xd5, 0x6e, 0x0a, 0x20, 0x46, 0x64, 0x5b, 0x51,
        0x63, 0x4e, 0x7a, 0x96, 0x96, 0x0c, 0x24, 0xee, 0x05, 0x97, 0x12, 0xca, 0x20, 0xdf, 0x05,
        0xd6, 0x50, 0x32, 0x90, 0x83, 0xb7, 0x06, 0xe5, 0x08, 0xcd, 0x98, 0xc4, 0x33, 0xcb, 0xaa,
        0x17, 0x45, 0x73, 0x8c, 0x01, 0x9e, 0xec, 0xe5,
    ];

    let vk_delta: [u8; 128] = [
        0x09, 0x87, 0x23, 0xf2, 0x8e, 0x48, 0x0f, 0x38, 0x54, 0xdb, 0xf3, 0x3d, 0x28, 0x2e, 0x9d,
        0x05, 0x8c, 0xa5, 0x66, 0x59, 0x98, 0xb8, 0xbf, 0x5c, 0xe5, 0x98, 0xbc, 0xe1, 0x77, 0xd5,
        0xf8, 0x17, 0x2c, 0x0c, 0x6d, 0xe5, 0x83, 0x89, 0x16, 0x26, 0x00, 0x86, 0xb4, 0x97, 0x5f,
        0xb2, 0x01, 0x0d, 0xca, 0x6b, 0x64, 0xc2, 0x41, 0xba, 0xc8, 0x81, 0xfa, 0xca, 0x10, 0x4d,
        0x16, 0x38, 0xd2, 0x19, 0x2c, 0x64, 0x1c, 0x6a, 0xa0, 0x59, 0x51, 0x55, 0x01, 0xb3, 0x9e,
        0xb2, 0x4b, 0xf9, 0x54, 0x58, 0xf9, 0xca, 0x25, 0xa0, 0x5c, 0x46, 0x26, 0xf3, 0x10, 0x9e,
        0x9c, 0xdf, 0x15, 0x3a, 0xe7, 0x2d, 0x06, 0xcf, 0x24, 0x04, 0xc1, 0x6f, 0xf3, 0xbc, 0xb4,
        0x0a, 0x96, 0x8b, 0xb0, 0x2d, 0x59, 0x00, 0xc6, 0x80, 0xae, 0x56, 0x4c, 0x64, 0xdd, 0xd0,
        0xaf, 0x9d, 0xeb, 0xf1, 0x0a, 0x2d, 0x49, 0x5a,
    ];

    // IC points for 8 public inputs (generated with OsRng)
    let vk_ic: [[u8; 64]; 9] = [
        // vk_ic[0]
        [
            0x1a, 0x29, 0xb4, 0xc0, 0xf3, 0xba, 0xe8, 0xf3, 0xf0, 0x96, 0x2e, 0xbe, 0x58, 0x50,
            0x71, 0xcf, 0x49, 0x19, 0xef, 0x3c, 0xb0, 0xda, 0xfe, 0x16, 0xeb, 0x35, 0x9e, 0x33,
            0xa2, 0xde, 0x05, 0xca, 0x2b, 0x3a, 0x18, 0x2f, 0x9c, 0x6c, 0x9d, 0x93, 0x5f, 0x0b,
            0x4b, 0x3d, 0xd4, 0x7c, 0x66, 0xc4, 0x75, 0x98, 0xcf, 0xd4, 0x95, 0x64, 0x4d, 0xb2,
            0x92, 0x10, 0x3b, 0x89, 0x53, 0x7a, 0x33, 0x72,
        ],
        // vk_ic[1] — identity_hash
        [
            0x1a, 0x1c, 0xbc, 0x28, 0xe5, 0x37, 0xf7, 0xec, 0xcf, 0xff, 0x67, 0x3c, 0x69, 0x83,
            0x3e, 0x52, 0x11, 0x20, 0xa7, 0x4f, 0xa9, 0xff, 0xe0, 0xf7, 0x9b, 0x32, 0xd1, 0x31,
            0x39, 0x98, 0x15, 0x2e, 0x2f, 0x0f, 0xcf, 0x63, 0x5b, 0xf0, 0x82, 0xb5, 0x20, 0x8a,
            0x42, 0xcb, 0xb7, 0x96, 0x0b, 0x7c, 0xd4, 0x91, 0x31, 0x24, 0x1f, 0xb0, 0xc8, 0x41,
            0xcb, 0xee, 0x5d, 0x66, 0xd0, 0xfb, 0x72, 0x14,
        ],
        // vk_ic[2] — nullifier_hash
        [
            0x09, 0xc7, 0x1e, 0xc8, 0xfe, 0xca, 0xea, 0x82, 0x61, 0xaf, 0xd3, 0x5f, 0x7d, 0x5f,
            0x16, 0x0d, 0x1f, 0xd0, 0x47, 0x9c, 0xa1, 0x6b, 0xab, 0xbe, 0x7e, 0xc5, 0xa9, 0x96,
            0xe2, 0x0a, 0x7e, 0x38, 0x20, 0xbd, 0x78, 0xbb, 0x40, 0xd4, 0x60, 0x58, 0x3f, 0xb1,
            0xf9, 0x54, 0xe3, 0xeb, 0x5b, 0x25, 0xc9, 0x38, 0x34, 0x74, 0xfa, 0x4f, 0x5c, 0xd1,
            0xb4, 0xfa, 0x8f, 0x10, 0x20, 0xed, 0x25, 0x3a,
        ],
        // vk_ic[3] — attestation_hash
        [
            0x06, 0xdb, 0x44, 0x0c, 0x76, 0x8f, 0xa2, 0x07, 0x14, 0x9f, 0x45, 0x9a, 0xa8, 0xdd,
            0x7c, 0xf5, 0xca, 0x03, 0x7d, 0x53, 0x03, 0xe6, 0x4c, 0x97, 0x2d, 0x6b, 0x86, 0xeb,
            0x3c, 0x13, 0x70, 0x03, 0x17, 0xd9, 0xc2, 0xfe, 0xda, 0xa6, 0x5b, 0xfe, 0x07, 0xde,
            0x25, 0x25, 0xdd, 0xfc, 0x62, 0x36, 0xe2, 0xc6, 0x7f, 0x90, 0x99, 0xef, 0xc0, 0xb8,
            0xa4, 0x89, 0x15, 0x6d, 0x58, 0xbd, 0xab, 0xd4,
        ],
        // vk_ic[4] — ciphertext_hash
        [
            0x11, 0xb3, 0x37, 0x9e, 0x89, 0x2e, 0x01, 0xd9, 0x93, 0x24, 0x00, 0x8d, 0xcb, 0x9a,
            0x53, 0x8f, 0x22, 0x1c, 0x47, 0x43, 0x0c, 0xf7, 0x35, 0x93, 0xba, 0x39, 0x04, 0xc3,
            0x36, 0x7e, 0xe9, 0x8a, 0x1c, 0x9c, 0xbc, 0xa1, 0x54, 0x35, 0xf3, 0x74, 0x0d, 0x92,
            0xad, 0x7b, 0x56, 0xe6, 0x32, 0x6d, 0x45, 0x14, 0xdb, 0x20, 0xc9, 0x3b, 0xb2, 0xce,
            0xe2, 0xbb, 0xe7, 0x75, 0xa6, 0x74, 0x22, 0x36,
        ],
        // vk_ic[5] — gateway_part1
        [
            0x17, 0xa4, 0xcb, 0xbf, 0xb1, 0x6d, 0xba, 0x00, 0x93, 0x0b, 0x8d, 0xf9, 0x6c, 0x7c,
            0xa5, 0x47, 0xc1, 0xfb, 0xae, 0xcf, 0x1e, 0x62, 0xba, 0x84, 0x35, 0x17, 0x50, 0x3d,
            0x2a, 0x2a, 0xb5, 0xc7, 0x19, 0x19, 0xb4, 0x07, 0x19, 0x84, 0x4a, 0x86, 0xd4, 0xd2,
            0x42, 0x1c, 0x8a, 0x81, 0xe8, 0x6d, 0xb9, 0x51, 0x3c, 0xd2, 0x45, 0xe5, 0xbe, 0x81,
            0xf5, 0x6a, 0x32, 0x25, 0x00, 0xe5, 0xe6, 0x51,
        ],
        // vk_ic[6] — gateway_part2
        [
            0x2f, 0x7e, 0x09, 0x8e, 0x72, 0xab, 0x31, 0xcd, 0xb3, 0x63, 0x51, 0x84, 0x37, 0xba,
            0x19, 0xb3, 0x6f, 0xf3, 0x32, 0x1c, 0x7e, 0xc4, 0x78, 0xd0, 0x92, 0xdf, 0x43, 0x2f,
            0x6d, 0xfc, 0x1c, 0xec, 0x0e, 0x76, 0x6d, 0xa7, 0x84, 0x52, 0x69, 0x60, 0xf4, 0x63,
            0xc1, 0x7e, 0xeb, 0x22, 0xbe, 0x29, 0xfa, 0xf2, 0x2e, 0x8a, 0xff, 0xf5, 0x62, 0x12,
            0x6d, 0x6b, 0x32, 0x01, 0x51, 0x59, 0x31, 0x69,
        ],
        // vk_ic[7] — deposit_commitment
        [
            0x17, 0xc0, 0x02, 0xd8, 0xee, 0xd4, 0x66, 0xbe, 0x47, 0x1a, 0x8d, 0x2c, 0x94, 0x43,
            0x95, 0x83, 0x3f, 0xdb, 0x45, 0x33, 0x6c, 0xce, 0x10, 0x6d, 0xf4, 0xa4, 0x39, 0x2d,
            0x68, 0x47, 0x91, 0x92, 0x29, 0x87, 0x8d, 0x1f, 0xad, 0x0d, 0x89, 0x22, 0x4d, 0xe4,
            0x05, 0x4c, 0xdd, 0xa8, 0xd3, 0x81, 0x5d, 0x80, 0x4e, 0xc3, 0xa0, 0x7b, 0xda, 0xe5,
            0xed, 0xaf, 0xec, 0xa6, 0x0d, 0x68, 0xe8, 0x03,
        ],
        // vk_ic[8] — firmware_hash_public
        [
            0x0f, 0x11, 0x1e, 0x9d, 0xbb, 0x09, 0xef, 0xbe, 0x41, 0x11, 0x94, 0xe0, 0x1b, 0xa9,
            0x6c, 0x97, 0x45, 0x3d, 0x1d, 0xad, 0x27, 0x7e, 0x79, 0xe4, 0x03, 0x96, 0xbc, 0x8a,
            0xd7, 0xb4, 0xac, 0xad, 0x11, 0x49, 0xb7, 0xb9, 0x5d, 0x29, 0x3c, 0x89, 0x04, 0xb8,
            0x81, 0x99, 0x10, 0x66, 0x14, 0xb4, 0x13, 0xa6, 0x5a, 0x9b, 0xae, 0x89, 0x9c, 0x71,
            0x1d, 0xea, 0xb6, 0x07, 0xe1, 0x27, 0x80, 0xf4,
        ],
    ];

    // Compute public input G1 point:
    // IC_total = vk_ic[0] + \sum_{i=0}^{7} public_inputs[i] * vk_ic[i+1]
    let mut current_ic = vk_ic[0];

    for i in 0..8 {
        let mut mul_input = [0u8; 96];
        mul_input[0..64].copy_from_slice(&vk_ic[i + 1]);
        for (dst, src) in mul_input[64..96]
            .iter_mut()
            .zip(public_inputs[i].iter().rev())
        {
            *dst = *src;
        }

        let scaled_point_vec = alt_bn128_multiplication(&mul_input)
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;
        let scaled_point: [u8; 64] = scaled_point_vec
            .try_into()
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;

        let mut add_input = [0u8; 128];
        add_input[0..64].copy_from_slice(&current_ic);
        add_input[64..128].copy_from_slice(&scaled_point);

        let added_point_vec = alt_bn128_addition(&add_input)
            .map_err(|_| error!(ZKLoRaError::InvalidZeroKnowledgeProof))?;
        current_ic = added_point_vec
            .try_into()
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

    if result
        != [
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 1,
        ]
    {
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
    pub nullifiers: Vec<[u8; 32]>,
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
    #[account(mut, address = ADMIN_AUTHORITY)]
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
#[instruction(public_inputs: [[u8; 32]; 8])]
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
              + (4 + 32 * MAX_BATCH_SIZE),
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
    #[account(
        seeds = [b"shielded-pool"],
        bump,
    )]
    pub shielded_pool: Account<'info, ShieldedEscrowPool>,
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
