// Watermark: ip zymatica.space | astronautshe.com
// Copyright (c) 2026 Zymatica / TheAiCollective.art. Licensed under Apache 2.0.
//
// ZK-LoRaWAN Solana Anchor Program — Dual Mode (Single + Batch)
// ==============================================================
//
// Two modes, user chooses:
//
//   MODE A — Single Chirp:
//     1 chirp = 1 Solana tx
//     Fee: 150,000 lamports + Solana base fee (~5,000)
//     Best for: low-volume devices, real-time verification
//
//   MODE B — Batch (up to 100 chirps):
//     N chirps = 1 Solana tx
//     Fee: 150,000 × N lamports + Solana base fee (~5,000)
//     Best for: high-volume devices, gateways with many clients
//     Saves: (N-1) × ~5,000 lamports in Solana base fees
//
// Gateway earnings are IDENTICAL in both modes:
//   100,000 lamports per chirp (always)
//   Treasury: 50,000 lamports per chirp (always)

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    keccak,
    system_instruction,
};

declare_id!("ZKLoRa1111111111111111111111111111111111111");

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
    // MODE A — Single Chirp Verification
    // ========================================================================
    // Client sends 1 chirp, pays 150,000 lamports, gets instant on-chain proof.
    // Gateway: +100,000 lamports | Treasury: +50,000 lamports
    // ========================================================================
    pub fn verify_single(
        ctx: Context<VerifySingle>,
        proof_hash: [u8; 32],
        payload_hash: [u8; 32],
        timestamp: i64,
    ) -> Result<()> {
        // Transfer gateway reward
        anchor_lang::solana_program::program::invoke(
            &system_instruction::transfer(
                &ctx.accounts.sender.key(),
                &ctx.accounts.gateway.key(),
                GATEWAY_REWARD_LAMPORTS,
            ),
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.gateway.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        // Transfer treasury fee
        anchor_lang::solana_program::program::invoke(
            &system_instruction::transfer(
                &ctx.accounts.sender.key(),
                &ctx.accounts.treasury.key(),
                PROTOCOL_FEE_LAMPORTS,
            ),
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.treasury.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        // Update registry
        let registry = &mut ctx.accounts.registry;
        registry.total_chirps_verified += 1;
        registry.total_fees_collected += TOTAL_FEE_PER_CHIRP;
        registry.total_gateway_rewards += GATEWAY_REWARD_LAMPORTS;
        registry.total_treasury_fees += PROTOCOL_FEE_LAMPORTS;

        msg!("ZK-LoRaWAN [SINGLE] chirp verified");
        msg!("  Proof hash:    {:?}...", &proof_hash[..4]);
        msg!("  Gateway:       +{} lamports", GATEWAY_REWARD_LAMPORTS);
        msg!("  Treasury:      +{} lamports", PROTOCOL_FEE_LAMPORTS);
        msg!("  Total charged: {} lamports", TOTAL_FEE_PER_CHIRP);
        Ok(())
    }

    // ========================================================================
    // MODE B — Batch Verification (3 instructions)
    // ========================================================================

    // B.1 — Initialize a new batch
    // Gateway opens a batch PDA. No fees charged yet.
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
    // Gateway adds proof hashes. No fees charged yet.
    // This can be called up to MAX_BATCH_SIZE times.
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

        msg!("ZK-LoRaWAN [BATCH] #{}: chirp {} added",
             batch.batch_id, batch.chirp_count);
        Ok(())
    }

    // B.3 — Submit (finalize) the batch
    // NOW fees are charged: 150,000 lamports × chirp_count
    // Gateway gets 100,000 × N, Treasury gets 50,000 × N
    // Merkle root computed and stored on-chain
    // ========================================================================
    pub fn submit_batch(ctx: Context<SubmitBatch>) -> Result<()> {
        let batch = &mut ctx.accounts.batch;

        require!(!batch.is_finalized, ZKLoRaError::BatchAlreadyFinalized);
        require!(batch.chirp_count > 0, ZKLoRaError::EmptyBatch);
        require!(
            batch.gateway == ctx.accounts.gateway.key(),
            ZKLoRaError::UnauthorizedGateway
        );

        let n = batch.chirp_count as u64;

        // Total fees: per-chirp fee × number of chirps
        let total_gateway_reward = GATEWAY_REWARD_LAMPORTS * n;
        let total_treasury_fee = PROTOCOL_FEE_LAMPORTS * n;
        let total_fee = total_gateway_reward + total_treasury_fee;

        // Transfer gateway reward (100,000 × N)
        anchor_lang::solana_program::program::invoke(
            &system_instruction::transfer(
                &ctx.accounts.sender.key(),
                &ctx.accounts.gateway.key(),
                total_gateway_reward,
            ),
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.gateway.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

        // Transfer treasury fee (40,000 × N)
        anchor_lang::solana_program::program::invoke(
            &system_instruction::transfer(
                &ctx.accounts.sender.key(),
                &ctx.accounts.treasury.key(),
                total_treasury_fee,
            ),
            &[
                ctx.accounts.sender.to_account_info(),
                ctx.accounts.treasury.to_account_info(),
                ctx.accounts.system_program.to_account_info(),
            ],
        )?;

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
        msg!("  Solana base fee: ~5,000 lamports (paid ONCE, not {} times)", n);
        msg!("  Savings:         ~{} lamports in base fees", 5_000 * (n - 1));
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
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct VerifySingle<'info> {
    #[account(mut, seeds = [REGISTRY_SEED], bump)]
    pub registry: Account<'info, ProtocolRegistry>,
    #[account(mut)]
    pub sender: Signer<'info>,
    /// CHECK: Gateway wallet receives reward
    #[account(mut)]
    pub gateway: AccountInfo<'info>,
    /// CHECK: Protocol treasury wallet
    #[account(mut)]
    pub treasury: AccountInfo<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeBatch<'info> {
    #[account(
        init,
        payer = gateway,
        space = 8 + 32 + 8 + 4 + 1 + 8 + 8 + 32
              + 4 + (32 * MAX_BATCH_SIZE)
              + 4 + (32 * MAX_BATCH_SIZE)
              + 4 + (8 * MAX_BATCH_SIZE),
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
    /// CHECK: Gateway wallet receives reward
    #[account(mut)]
    pub gateway: AccountInfo<'info>,
    /// CHECK: Protocol treasury wallet
    #[account(mut)]
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
}
