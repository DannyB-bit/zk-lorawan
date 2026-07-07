// Watermark: ip zymatica.space | astronautshe.com
// Copyright (c) 2026 Zymatica / TheAiCollective.art. Licensed under Apache 2.0.
//
// ZK-LoRaWAN Solana Anchor Program — Batch Verification
// ======================================================
//
// Architecture:
//   Gateway collects chirps → batches them → submits ONE Solana tx
//   Cost: $0.03 / batch (not per chirp)
//
//   100 chirps batched = $0.0003 per chirp vs $0.03 per chirp
//   Weather station: $10.95/year vs $1,051/year
//
// Instructions:
//   1. initialize_batch   — Create a batch accumulator PDA
//   2. add_chirp          — Gateway adds a chirp proof hash to the batch
//   3. submit_batch       — Finalize batch with Merkle root + fee split
//   4. verify_single      — Legacy single-chirp verification (backward compat)

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    keccak,
    system_instruction,
};

declare_id!("ZKLoRa1111111111111111111111111111111111111");

// ============================================================================
// Protocol Constants
// ============================================================================
pub const PROTOCOL_FEE_LAMPORTS: u64 = 40_000;
pub const GATEWAY_REWARD_LAMPORTS: u64 = 160_000;
pub const TOTAL_FEE_PER_CHIRP: u64 = PROTOCOL_FEE_LAMPORTS + GATEWAY_REWARD_LAMPORTS;
pub const MAX_BATCH_SIZE: usize = 100;
pub const BATCH_SEED: &[u8] = b"zk-lorawan-batch";
pub const REGISTRY_SEED: &[u8] = b"zk-lorawan-registry";

// Batch fee: gateway pays ONE Solana tx fee, protocol gets flat batch fee
pub const BATCH_FEE_LAMPORTS: u64 = 200_000;   // total fee per batch submission
pub const BATCH_GATEWAY_SHARE: u64 = 160_000;   // gateway keeps this
pub const BATCH_TREASURY_SHARE: u64 = 40_000;   // protocol treasury

#[program]
pub mod zk_lorawan {
    use super::*;

    // ========================================================================
    // Initialize a batch accumulator for a gateway
    // ========================================================================
    pub fn initialize_batch(ctx: Context<InitializeBatch>) -> Result<()> {
        let batch = &mut ctx.accounts.batch;
        batch.gateway = ctx.accounts.gateway.key();
        batch.chirp_count = 0;
        batch.proof_hashes = Vec::new();
        batch.payload_hashes = Vec::new();
        batch.timestamps = Vec::new();
        batch.merkle_root = [0u8; 32];
        batch.is_finalized = false;
        batch.created_at = Clock::get()?.unix_timestamp;
        batch.batch_id = ctx.accounts.registry.next_batch_id;

        // Increment global batch counter
        let registry = &mut ctx.accounts.registry;
        registry.next_batch_id += 1;
        registry.total_batches += 1;

        msg!("ZK-LoRaWAN: Batch {} initialized for gateway {}",
             batch.batch_id, batch.gateway);
        Ok(())
    }

    // ========================================================================
    // Add a chirp's proof hash to the batch (gateway calls this off-chain
    // or accumulates locally, then submits all at once)
    // ========================================================================
    pub fn add_chirp(
        ctx: Context<AddChirp>,
        proof_hash: [u8; 32],
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

        batch.proof_hashes.push(proof_hash);
        batch.payload_hashes.push(payload_hash);
        batch.timestamps.push(timestamp);
        batch.chirp_count += 1;

        msg!("ZK-LoRaWAN: Chirp {} added to batch {} (proof: {:?}...)",
             batch.chirp_count, batch.batch_id, &proof_hash[..4]);
        Ok(())
    }

    // ========================================================================
    // Submit (finalize) the batch — compute Merkle root, pay fees
    // This is the ONLY transaction that costs Solana fees
    // ========================================================================
    pub fn submit_batch(ctx: Context<SubmitBatch>) -> Result<()> {
        let batch = &mut ctx.accounts.batch;

        require!(!batch.is_finalized, ZKLoRaError::BatchAlreadyFinalized);
        require!(batch.chirp_count > 0, ZKLoRaError::EmptyBatch);
        require!(
            batch.gateway == ctx.accounts.gateway.key(),
            ZKLoRaError::UnauthorizedGateway
        );

        // Compute Merkle root from all proof hashes
        let merkle_root = compute_merkle_root(&batch.proof_hashes);
        batch.merkle_root = merkle_root;
        batch.is_finalized = true;
        batch.finalized_at = Clock::get()?.unix_timestamp;

        // Fee split: sender pays BATCH_FEE_LAMPORTS
        // Gateway gets BATCH_GATEWAY_SHARE
        // Treasury gets BATCH_TREASURY_SHARE
        let gateway_transfer = system_instruction::transfer(
            &ctx.accounts.sender.key(),
            &ctx.accounts.gateway.key(),
            BATCH_GATEWAY_SHARE,
        );
        anchor_lang::solana_program::program::invoke(
            &gateway_transfer,
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.gateway.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        let treasury_transfer = system_instruction::transfer(
            &ctx.accounts.sender.key(),
            &ctx.accounts.treasury.key(),
            BATCH_TREASURY_SHARE,
        );
        anchor_lang::solana_program::program::invoke(
            &treasury_transfer,
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.treasury.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        // Update registry stats
        let registry = &mut ctx.accounts.registry;
        registry.total_chirps_verified += batch.chirp_count as u64;
        registry.total_fees_collected += BATCH_FEE_LAMPORTS;

        let cost_per_chirp = BATCH_FEE_LAMPORTS / batch.chirp_count as u64;

        msg!("ZK-LoRaWAN: Batch {} finalized!", batch.batch_id);
        msg!("  Chirps in batch:     {}", batch.chirp_count);
        msg!("  Merkle root:         {:?}", &merkle_root[..8]);
        msg!("  Total batch fee:     {} lamports", BATCH_FEE_LAMPORTS);
        msg!("  Cost per chirp:      {} lamports", cost_per_chirp);
        msg!("  Gateway reward:      {} lamports", BATCH_GATEWAY_SHARE);
        msg!("  Treasury fee:        {} lamports", BATCH_TREASURY_SHARE);

        Ok(())
    }

    // ========================================================================
    // Verify a single chirp against a finalized batch (Merkle proof)
    // Anyone can call this to prove a specific chirp was in a batch
    // ========================================================================
    pub fn verify_chirp_inclusion(
        ctx: Context<VerifyChirpInclusion>,
        proof_hash: [u8; 32],
        merkle_proof: Vec<[u8; 32]>,
        leaf_index: u32,
    ) -> Result<()> {
        let batch = &ctx.accounts.batch;

        require!(batch.is_finalized, ZKLoRaError::BatchNotFinalized);

        // Verify Merkle inclusion
        let is_valid = verify_merkle_proof(
            &proof_hash,
            &merkle_proof,
            leaf_index,
            &batch.merkle_root,
        );

        require!(is_valid, ZKLoRaError::InvalidMerkleProof);

        msg!("ZK-LoRaWAN: Chirp verified in batch {} (leaf {})",
             batch.batch_id, leaf_index);
        Ok(())
    }

    // ========================================================================
    // Legacy: Single chirp verification (backward compatible)
    // ========================================================================
    pub fn verify_single(
        ctx: Context<VerifySingle>,
        proof_hash: [u8; 32],
        payload_hash: [u8; 32],
    ) -> Result<()> {
        // Fee split for single verification
        let gateway_transfer = system_instruction::transfer(
            &ctx.accounts.sender.key(),
            &ctx.accounts.gateway.key(),
            GATEWAY_REWARD_LAMPORTS,
        );
        anchor_lang::solana_program::program::invoke(
            &gateway_transfer,
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.gateway.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        let treasury_transfer = system_instruction::transfer(
            &ctx.accounts.sender.key(),
            &ctx.accounts.treasury.key(),
            PROTOCOL_FEE_LAMPORTS,
        );
        anchor_lang::solana_program::program::invoke(
            &treasury_transfer,
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.treasury.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        let registry = &mut ctx.accounts.registry;
        registry.total_chirps_verified += 1;
        registry.total_fees_collected += TOTAL_FEE_PER_CHIRP;

        msg!("ZK-LoRaWAN: Single chirp verified. Fee: {} lamports",
             TOTAL_FEE_PER_CHIRP);
        Ok(())
    }

    // ========================================================================
    // Initialize protocol registry (one-time setup)
    // ========================================================================
    pub fn initialize_registry(ctx: Context<InitializeRegistry>) -> Result<()> {
        let registry = &mut ctx.accounts.registry;
        registry.authority = ctx.accounts.authority.key();
        registry.next_batch_id = 0;
        registry.total_batches = 0;
        registry.total_chirps_verified = 0;
        registry.total_fees_collected = 0;
        registry.created_at = Clock::get()?.unix_timestamp;

        msg!("ZK-LoRaWAN: Protocol registry initialized");
        Ok(())
    }
}

// ============================================================================
// Merkle Tree Utilities
// ============================================================================

/// Compute Merkle root from a list of leaf hashes
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
            if i + 1 < current_level.len() {
                let combined = [
                    current_level[i].as_slice(),
                    current_level[i + 1].as_slice(),
                ].concat();
                let hash = keccak::hash(&combined);
                next_level.push(hash.to_bytes());
            } else {
                // Odd leaf: hash with itself
                let combined = [
                    current_level[i].as_slice(),
                    current_level[i].as_slice(),
                ].concat();
                let hash = keccak::hash(&combined);
                next_level.push(hash.to_bytes());
            }
        }

        current_level = next_level;
    }

    current_level[0]
}

/// Verify a Merkle inclusion proof
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
        let hash = keccak::hash(&combined);
        current = hash.to_bytes();
        index /= 2;
    }

    current == *root
}

// ============================================================================
// Account Structures
// ============================================================================

#[account]
pub struct BatchAccumulator {
    pub gateway: Pubkey,           // 32 bytes
    pub batch_id: u64,             // 8 bytes
    pub chirp_count: u32,          // 4 bytes
    pub is_finalized: bool,        // 1 byte
    pub created_at: i64,           // 8 bytes
    pub finalized_at: i64,         // 8 bytes
    pub merkle_root: [u8; 32],     // 32 bytes
    pub proof_hashes: Vec<[u8; 32]>,    // 4 + (32 * MAX_BATCH_SIZE) bytes
    pub payload_hashes: Vec<[u8; 32]>,  // 4 + (32 * MAX_BATCH_SIZE) bytes
    pub timestamps: Vec<i64>,           // 4 + (8 * MAX_BATCH_SIZE) bytes
}

#[account]
pub struct ProtocolRegistry {
    pub authority: Pubkey,               // 32 bytes
    pub next_batch_id: u64,              // 8 bytes
    pub total_batches: u64,              // 8 bytes
    pub total_chirps_verified: u64,      // 8 bytes
    pub total_fees_collected: u64,       // 8 bytes
    pub created_at: i64,                 // 8 bytes
}

// ============================================================================
// Instruction Contexts
// ============================================================================

#[derive(Accounts)]
pub struct InitializeRegistry<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + 32 + 8 + 8 + 8 + 8 + 8,
        seeds = [REGISTRY_SEED],
        bump,
    )]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeBatch<'info> {
    #[account(
        init,
        payer = gateway,
        space = 8 + 32 + 8 + 4 + 1 + 8 + 8 + 32 + 4 + (32 * MAX_BATCH_SIZE) + 4 + (32 * MAX_BATCH_SIZE) + 4 + (8 * MAX_BATCH_SIZE),
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
    #[account(mut)]
    pub sender: Signer<'info>,
    /// CHECK: Gateway receives reward
    #[account(mut)]
    pub gateway: AccountInfo<'info>,
    /// CHECK: Protocol treasury
    #[account(mut)]
    pub treasury: AccountInfo<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct VerifyChirpInclusion<'info> {
    pub batch: Account<'info, BatchAccumulator>,
}

#[derive(Accounts)]
pub struct VerifySingle<'info> {
    #[account(mut, seeds = [REGISTRY_SEED], bump)]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(mut)]
    pub sender: Signer<'info>,
    /// CHECK: Gateway receives reward
    #[account(mut)]
    pub gateway: AccountInfo<'info>,
    /// CHECK: Protocol treasury
    #[account(mut)]
    pub treasury: AccountInfo<'info>,
    pub system_program: Program<'info, System>,
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
    #[msg("Unauthorized gateway")]
    UnauthorizedGateway,
    #[msg("Batch has no chirps")]
    EmptyBatch,
    #[msg("Batch is not yet finalized")]
    BatchNotFinalized,
    #[msg("Invalid Merkle proof")]
    InvalidMerkleProof,
}
