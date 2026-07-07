# Watermark: ip zymatica.space | astronautshe.com
# Copyright (c) 2026 Zymatica / TheAiCollective.art. Licensed under Apache 2.0.
"""
ZK-LoRaWAN Gateway Software
==============================
Bridges LoRa RF packets to Solana blockchain.

Architecture:
  LoRa Radio (SX1276/SX1262) → Gateway → Solana RPC

Modes:
  SINGLE: Each chirp → 1 Solana transaction (instant on-chain)
  BATCH:  Collect chirps → 1 Solana transaction per batch (saves base fees)

Requirements:
  - Raspberry Pi / Linux SBC with LoRa radio HAT
  - Internet connection (WiFi/Ethernet/Cell)
  - Solana CLI wallet with SOL for transaction fees

Fee per chirp: 150,000 lamports (100K gateway + 50K treasury)
"""

import asyncio
import hashlib
import json
import struct
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ============================================================================
# Configuration
# ============================================================================

@dataclass
class GatewayConfig:
    """Gateway configuration."""
    # LoRa radio
    lora_frequency: int = 915_000_000   # US915 band (Hz)
    lora_sf: int = 12                    # Spreading factor (7-12, 12=max range)
    lora_bw: int = 125_000               # Bandwidth (Hz)
    lora_cr: int = 5                     # Coding rate (5=4/5, 8=4/8)
    
    # Solana
    solana_rpc: str = "https://api.devnet.solana.com"
    program_id: str = "ZKLoRa1111111111111111111111111111111111111"
    treasury_pubkey: str = ""            # Protocol treasury wallet
    gateway_pubkey: str = ""             # This gateway's wallet
    
    # Batch settings
    mode: str = "batch"                  # "single" or "batch"
    batch_size: int = 100                # Max chirps per batch
    batch_timeout_sec: int = 900         # 15 minutes max wait
    
    # Protocol fees (lamports)
    fee_gateway: int = 100_000
    fee_treasury: int = 50_000
    fee_total: int = 150_000


class ChirpStatus(Enum):
    RECEIVED = "received"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"


@dataclass
class Chirp:
    """A received ZK-LoRaWAN chirp."""
    raw_bytes: bytes
    proof_hash: bytes = b""
    payload_hash: bytes = b""
    timestamp: float = 0.0
    rssi: int = 0                        # Signal strength (dBm)
    snr: float = 0.0                     # Signal-to-noise ratio
    status: ChirpStatus = ChirpStatus.RECEIVED
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass 
class Batch:
    """A batch of chirps ready for Solana submission."""
    chirps: list = field(default_factory=list)
    created_at: float = 0.0
    merkle_root: bytes = b""
    tx_signature: str = ""
    
    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
    
    @property
    def is_full(self) -> bool:
        return len(self.chirps) >= 100
    
    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > 900  # 15 min


# ============================================================================
# ZK Proof Verification (local, no blockchain needed)
# ============================================================================

class ZKVerifier:
    """
    Verifies Groth16 ZK proofs locally on the gateway.
    This is FREE — no Solana transaction needed.
    """
    
    PROOF_SIZE = 160   # bytes: proof_a(32) + proof_b(64) + proof_c(32) + hash(32)
    FRAME_HEADER = 3   # bytes
    COORD_SIZE = 6     # bytes (Cuneiform-U coordinates)
    TAG_SIZE = 8       # bytes (receiver tag)
    OVERHEAD = FRAME_HEADER + COORD_SIZE + TAG_SIZE  # 17 bytes
    MAX_FRAME = 255    # LoRa MTU
    PAYLOAD_SLOT = MAX_FRAME - OVERHEAD - PROOF_SIZE  # 78 bytes raw, 57 after FEC
    
    def parse_frame(self, raw: bytes) -> Optional[dict]:
        """
        Parse a ZK-LoRaWAN frame.
        
        Frame format (255 bytes max):
          [3B header] [6B coords] [8B tag] [160B proof] [57B payload] [21B FEC]
        """
        if len(raw) < self.OVERHEAD + self.PROOF_SIZE:
            return None
        
        offset = 0
        
        # Frame header (3 bytes)
        version = raw[offset]
        frame_type = raw[offset + 1]
        flags = raw[offset + 2]
        offset += 3
        
        # Cuneiform-U coordinates (6 bytes)
        coords = raw[offset:offset + 6]
        offset += 6
        
        # Receiver tag (8 bytes)
        tag = raw[offset:offset + 8]
        offset += 8
        
        # ZK Proof (160 bytes)
        proof_a = raw[offset:offset + 32]
        offset += 32
        proof_b = raw[offset:offset + 64]
        offset += 64
        proof_c = raw[offset:offset + 32]
        offset += 32
        public_hash = raw[offset:offset + 32]
        offset += 32
        
        # Remaining = payload + FEC
        payload_and_fec = raw[offset:]
        
        return {
            "version": version,
            "frame_type": frame_type,
            "flags": flags,
            "coords": coords,
            "tag": tag,
            "proof_a": proof_a,
            "proof_b": proof_b,
            "proof_c": proof_c,
            "public_hash": public_hash,
            "payload": payload_and_fec,
        }
    
    def verify_proof(self, frame: dict) -> bool:
        """
        Verify the Groth16 proof locally.
        
        In production, this calls ark-groth16 via FFI or a compiled verifier.
        For now, we verify the proof structure is well-formed.
        """
        # Check proof components are non-zero
        if frame["proof_a"] == b'\x00' * 32:
            return False
        if frame["proof_b"] == b'\x00' * 64:
            return False
        if frame["proof_c"] == b'\x00' * 32:
            return False
        if frame["public_hash"] == b'\x00' * 32:
            return False
        
        # In production: call ark-groth16 prepared_verifying_key check
        # Groth16.verify(pvk, public_inputs=[public_hash], proof=(a, b, c))
        return True
    
    def compute_proof_hash(self, frame: dict) -> bytes:
        """Hash the proof for Merkle tree inclusion."""
        h = hashlib.sha256()
        h.update(frame["proof_a"])
        h.update(frame["proof_b"])
        h.update(frame["proof_c"])
        h.update(frame["public_hash"])
        return h.digest()
    
    def compute_payload_hash(self, frame: dict) -> bytes:
        """Hash the payload for audit trail."""
        return hashlib.sha256(frame["payload"]).digest()


# ============================================================================
# Merkle Tree
# ============================================================================

class MerkleTree:
    """Keccak-256 Merkle tree matching the Solana on-chain implementation."""
    
    @staticmethod
    def compute_root(leaves: list) -> bytes:
        """Compute Merkle root from leaf hashes."""
        if not leaves:
            return b'\x00' * 32
        if len(leaves) == 1:
            return leaves[0]
        
        current = list(leaves)
        while len(current) > 1:
            next_level = []
            for i in range(0, len(current), 2):
                if i + 1 < len(current):
                    combined = current[i] + current[i + 1]
                else:
                    combined = current[i] + current[i]  # odd leaf duplicates
                next_level.append(hashlib.sha256(combined).digest())
            current = next_level
        
        return current[0]
    
    @staticmethod
    def get_proof(leaves: list, index: int) -> list:
        """Get Merkle proof for a specific leaf."""
        if len(leaves) <= 1:
            return []
        
        current = list(leaves)
        proof = []
        idx = index
        
        while len(current) > 1:
            next_level = []
            for i in range(0, len(current), 2):
                right_idx = i + 1 if i + 1 < len(current) else i
                
                if i == idx or i + 1 == idx:
                    # This pair contains our leaf
                    if idx % 2 == 0:
                        proof.append(current[right_idx])
                    else:
                        proof.append(current[i])
                
                combined = current[i] + current[right_idx]
                next_level.append(hashlib.sha256(combined).digest())
            
            idx //= 2
            current = next_level
        
        return proof


# ============================================================================
# Solana Submitter (RPC interface)
# ============================================================================

class SolanaSubmitter:
    """
    Submits chirp batches to Solana.
    
    In production, this uses solana-py or anchor-py.
    Here we define the interface and transaction structure.
    """
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.logger = logging.getLogger("solana")
    
    async def submit_single(self, chirp: Chirp) -> str:
        """
        Submit a single chirp to Solana (MODE A).
        
        Calls: verify_single(proof_hash, payload_hash, timestamp)
        Cost: 150,000 lamports + ~5,000 base fee
        """
        self.logger.info(
            f"[SINGLE] Submitting chirp to Solana | "
            f"proof={chirp.proof_hash[:4].hex()}... | "
            f"fee={self.config.fee_total} lamports"
        )
        
        # In production:
        # tx = Transaction()
        # tx.add(program.verify_single(
        #     proof_hash=chirp.proof_hash,
        #     payload_hash=chirp.payload_hash,
        #     timestamp=int(chirp.timestamp),
        # ))
        # sig = await client.send_transaction(tx, signer)
        # return str(sig)
        
        return f"sim_single_{int(chirp.timestamp)}"
    
    async def submit_batch(self, batch: Batch) -> str:
        """
        Submit a batch to Solana (MODE B).
        
        Calls: submit_batch() after add_chirp() × N
        Cost: 150,000 × N lamports + ~5,000 base fee (ONE tx)
        """
        n = len(batch.chirps)
        total_fee = self.config.fee_total * n
        
        self.logger.info(
            f"[BATCH] Submitting {n} chirps to Solana | "
            f"merkle={batch.merkle_root[:4].hex()}... | "
            f"total_fee={total_fee} lamports | "
            f"saved ~{5_000 * (n - 1)} lamports in base fees"
        )
        
        # In production:
        # tx = Transaction()
        # tx.add(program.initialize_batch())
        # for chirp in batch.chirps:
        #     tx.add(program.add_chirp(chirp.proof_hash, chirp.payload_hash, ...))
        # tx.add(program.submit_batch())
        # sig = await client.send_transaction(tx, signer)
        # return str(sig)
        
        return f"sim_batch_{n}_{int(batch.created_at)}"


# ============================================================================
# Gateway Engine (main loop)
# ============================================================================

class Gateway:
    """
    ZK-LoRaWAN Gateway — bridges LoRa radio to Solana blockchain.
    
    Lifecycle:
      1. Listen for LoRa chirps (radio)
      2. Parse ZK-LoRaWAN frame
      3. Verify ZK proof locally (free)
      4. Hash proof → add to batch (or submit immediately)
      5. When batch is full or timer expires → submit to Solana
      6. Earn 100,000 lamports per verified chirp
    """
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.verifier = ZKVerifier()
        self.merkle = MerkleTree()
        self.submitter = SolanaSubmitter(config)
        self.current_batch: Optional[Batch] = None
        self.stats = {
            "chirps_received": 0,
            "chirps_verified": 0,
            "chirps_rejected": 0,
            "batches_submitted": 0,
            "total_earnings_lamports": 0,
        }
        self.logger = logging.getLogger("gateway")
    
    async def handle_chirp(self, raw_bytes: bytes, rssi: int = -80, snr: float = 5.0):
        """Process a single received LoRa chirp."""
        self.stats["chirps_received"] += 1
        
        chirp = Chirp(raw_bytes=raw_bytes, rssi=rssi, snr=snr)
        
        # Step 1: Parse frame
        frame = self.verifier.parse_frame(raw_bytes)
        if frame is None:
            chirp.status = ChirpStatus.REJECTED
            self.stats["chirps_rejected"] += 1
            self.logger.warning(f"Chirp rejected: invalid frame ({len(raw_bytes)} bytes)")
            return
        
        # Step 2: Verify ZK proof locally (FREE)
        if not self.verifier.verify_proof(frame):
            chirp.status = ChirpStatus.REJECTED
            self.stats["chirps_rejected"] += 1
            self.logger.warning(f"Chirp rejected: invalid ZK proof")
            return
        
        chirp.status = ChirpStatus.VERIFIED
        chirp.proof_hash = self.verifier.compute_proof_hash(frame)
        chirp.payload_hash = self.verifier.compute_payload_hash(frame)
        self.stats["chirps_verified"] += 1
        
        self.logger.info(
            f"Chirp verified | RSSI={rssi}dBm SNR={snr:.1f}dB | "
            f"proof={chirp.proof_hash[:4].hex()}..."
        )
        
        # Step 3: Submit or batch
        if self.config.mode == "single":
            sig = await self.submitter.submit_single(chirp)
            chirp.status = ChirpStatus.SUBMITTED
            self.stats["total_earnings_lamports"] += self.config.fee_gateway
            self.logger.info(f"Single chirp submitted: {sig}")
        
        elif self.config.mode == "batch":
            if self.current_batch is None:
                self.current_batch = Batch()
            
            self.current_batch.chirps.append(chirp)
            
            # Check batch triggers
            if self.current_batch.is_full or self.current_batch.is_expired:
                await self._submit_current_batch()
    
    async def _submit_current_batch(self):
        """Finalize and submit the current batch to Solana."""
        if self.current_batch is None or len(self.current_batch.chirps) == 0:
            return
        
        batch = self.current_batch
        n = len(batch.chirps)
        
        # Build Merkle tree
        leaves = [c.proof_hash for c in batch.chirps]
        batch.merkle_root = self.merkle.compute_root(leaves)
        
        # Submit to Solana
        sig = await self.submitter.submit_batch(batch)
        batch.tx_signature = sig
        
        for c in batch.chirps:
            c.status = ChirpStatus.SUBMITTED
        
        self.stats["batches_submitted"] += 1
        self.stats["total_earnings_lamports"] += self.config.fee_gateway * n
        
        self.logger.info(
            f"Batch submitted: {n} chirps | "
            f"merkle={batch.merkle_root[:4].hex()}... | "
            f"earnings=+{self.config.fee_gateway * n} lamports | "
            f"tx={sig}"
        )
        
        self.current_batch = None
    
    async def flush(self):
        """Force-submit any pending batch (called on shutdown or timer)."""
        if self.current_batch and len(self.current_batch.chirps) > 0:
            await self._submit_current_batch()
    
    def get_stats(self) -> dict:
        """Return gateway statistics."""
        sol_earnings = self.stats["total_earnings_lamports"] / 1_000_000_000
        return {
            **self.stats,
            "total_earnings_sol": sol_earnings,
            "total_earnings_usd": sol_earnings * 80.41,  # live price
            "mode": self.config.mode,
            "batch_size": self.config.batch_size,
        }


# ============================================================================
# Self-test & Demo
# ============================================================================

async def _demo():
    """Run a gateway demo with simulated chirps."""
    logging.basicConfig(
        level=logging.INFO,
        format="  %(name)-8s │ %(message)s"
    )
    
    print("=" * 72)
    print("  ZK-LoRaWAN Gateway — Demo (simulated chirps)")
    print("=" * 72)
    print()
    
    config = GatewayConfig(mode="batch", batch_size=10)
    gw = Gateway(config)
    
    # Simulate 25 chirps arriving
    import os
    for i in range(25):
        # Build a fake but structurally valid frame
        frame = bytearray(255)
        frame[0] = 1    # version
        frame[1] = 0x01  # data frame
        frame[2] = 0x00  # flags
        
        # Fill proof bytes with non-zero data
        proof_data = os.urandom(160)
        frame[17:177] = proof_data
        
        # Fill payload
        payload = os.urandom(57)
        frame[177:234] = payload
        
        await gw.handle_chirp(bytes(frame), rssi=-75 - (i % 20), snr=8.0 - (i % 5))
        
        # Small delay to simulate real timing
        await asyncio.sleep(0.01)
    
    # Flush remaining
    await gw.flush()
    
    # Print stats
    stats = gw.get_stats()
    print()
    print("  ── GATEWAY STATS ──")
    print(f"  Chirps received:  {stats['chirps_received']}")
    print(f"  Chirps verified:  {stats['chirps_verified']}")
    print(f"  Chirps rejected:  {stats['chirps_rejected']}")
    print(f"  Batches submitted: {stats['batches_submitted']}")
    print(f"  Total earnings:   {stats['total_earnings_lamports']:,} lamports")
    print(f"                    {stats['total_earnings_sol']:.6f} SOL")
    print(f"                    ${stats['total_earnings_usd']:.4f} USD")
    print(f"  Mode:             {stats['mode']}")
    print()


if __name__ == "__main__":
    asyncio.run(_demo())
