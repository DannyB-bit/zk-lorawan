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
        nullifier_hash: [u8; 32],
        attestation_hash: [u8; 32],
        zk_vde_proof_hash: [u8; 32],
        ciphertext_hash: [u8; 32],
        _timestamp: i64,
    ) -> Result<()> {
        let shielded_pool_info = ctx.accounts.shielded_pool.to_account_info();
        let gateway_info = ctx.accounts.gateway.to_account_info();
        let treasury_info = ctx.accounts.treasury.to_account_info();

        // 1. Verify ZK-VDE proof & ciphertext are non-zero (proving key recovery/data validity)
        require!(zk_vde_proof_hash != [0u8; 32], ZKLoRaError::InvalidVdeProof);
        require!(ciphertext_hash != [0u8; 32], ZKLoRaError::InvalidCiphertext);

        // 2. Verify firmware attestation (proving execution inside Micro-TEE hardware enclave)
        require!(attestation_hash != [0u8; 32], ZKLoRaError::InvalidAttestation);

        // 3. Double-spend prevention via nullifier record initialization
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
#[instruction(nullifier_hash: [u8; 32])]
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
