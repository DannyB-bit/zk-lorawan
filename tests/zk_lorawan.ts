import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { ZkLorawan } from "../target/types/zk_lorawan";
import { assert } from "chai";
import * as crypto from "crypto";
import { keccak_256 } from "@noble/hashes/sha3";

function buildMerkleProof(leaves: Buffer[], leafIndex: number): Buffer[] {
  let proof: Buffer[] = [];
  let currentLevel = [...leaves];
  let index = leafIndex;

  while (currentLevel.length > 1) {
    let nextLevel: Buffer[] = [];
    for (let i = 0; i < currentLevel.length; i += 2) {
      let left = currentLevel[i];
      let right = i + 1 < currentLevel.length ? currentLevel[i + 1] : left;
      
      if (i === index || i + 1 === index) {
        let sibling = i === index ? right : left;
        proof.push(sibling);
      }
      
      let combined = Buffer.concat([left, right]);
      nextLevel.push(Buffer.from(keccak_256(combined)));
    }
    currentLevel = nextLevel;
    index = Math.floor(index / 2);
  }
  return proof;
}


describe("zk_lorawan", () => {
  // Configure the client to use the local cluster.
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace.ZkLorawan as Program<ZkLorawan>;

  // Generate keypairs for our actors
  const gateway = anchor.web3.Keypair.generate();
  const sender = anchor.web3.Keypair.generate();

  // Hardcoded treasury address matching lib.rs
  const treasuryAddress = new anchor.web3.PublicKey("CotbUcSMqaqn69YSmh2YgYZjKfE7cZk4fTsEmE3kfWJ");

  // Find PDA for registry
  const [registryPda, registryBump] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("zk-lorawan-registry")],
    program.programId
  );

  // Find PDA for the global shielded pool
  const [shieldedPoolPda, shieldedPoolBump] = anchor.web3.PublicKey.findProgramAddressSync(
    [Buffer.from("shielded-pool")],
    program.programId
  );

  before(async () => {
    // Airdrop SOL to sender and gateway to cover transaction fees and rent
    const signature1 = await provider.connection.requestAirdrop(
      sender.publicKey,
      5 * anchor.web3.LAMPORTS_PER_SOL
    );
    await provider.connection.confirmTransaction(signature1);

    const signature2 = await provider.connection.requestAirdrop(
      gateway.publicKey,
      5 * anchor.web3.LAMPORTS_PER_SOL
    );
    await provider.connection.confirmTransaction(signature2);
  });

  it("Initializes the global registry", async () => {
    await program.methods
      .initializeRegistry()
      .accounts({
        registry: registryPda,
        authority: provider.wallet.publicKey,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .rpc();

    const registryAccount = await program.account.protocolRegistry.fetch(registryPda);
    assert.ok(registryAccount.authority.equals(provider.wallet.publicKey));
    assert.equal(registryAccount.nextBatchId.toNumber(), 0);
  });

  it("Deposits SOL into the Shared Shielded Pool", async () => {
    const amount = new anchor.BN(2 * anchor.web3.LAMPORTS_PER_SOL);
    const dummyLeafHash = Array.from(crypto.randomBytes(32));

    await program.methods
      .depositShielded(amount, dummyLeafHash)
      .accounts({
        sender: sender.publicKey,
        shieldedPool: shieldedPoolPda,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([sender])
      .rpc();

    const poolAccount = await program.account.shieldedEscrowPool.fetch(shieldedPoolPda);
    assert.isTrue(poolAccount.totalBalance.toNumber() >= amount.toNumber());
    assert.deepEqual(poolAccount.merkleRoot, dummyLeafHash);
  });

  it("Performs single shielded chirp verification (MODE A)", async () => {
    const nullifierHash = Buffer.from("07d01f9518cbe729b68dc48eba185c6a08a5d2a6a75646d69cf79d9157efc81b", "hex");
    const attestationHash = Buffer.from("74e8623e16cda398f38ae0f520634f4fa27e52b5fe08afbfb7ef552d379c7318", "hex");
    const zkVdeProofHash = Buffer.from("7340a9115677e6b1faec90248ae27b7a94f8067fcf7d5a54034df69626da3708", "hex");
    const ciphertextHash = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");
    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

    // Real, mathematically verified Groth16 proof coordinates
    const proofA = Buffer.from("282116dbe4c86377596b9a58b601aa6f53a631ac55aea2d0b5082554cc6906e90d145795ae065f88d499c232cb92f697f76c4765bc35b1449d572bf5458b44c5", "hex");
    const proofB = Buffer.from("16765162f38ec6cc7cc58bb27daa60a2d54972ced1fe11ca579542c76a374b0620381e31440a773b8415bf9bdcb0b969aab65daa51ef1c60c00f517b3b23fc2b07809e3cf0b0886e40595f146f0a2dfa42b015d9a9d734bd223634aeb02b03f52c4892514ffc887ae1b490d9348f93f7c234e6d06c864b6b5939e7869622007d", "hex");
    const proofC = Buffer.from("238e7f48a79cde9d573ab0b2060ff4c14d44a5896d29b91036993fd72eb45d7f0a774f8a5983cbf4b5be6cf49c5aac27408f4775cadc80735a3d521004f641c9", "hex");

    // Find PDA for nullifier record
    const [nullifierRecordPda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("nullifier"), nullifierHash],
      program.programId
    );

    // Get initial balances
    const initialGatewayBal = await provider.connection.getBalance(gateway.publicKey);
    const initialTreasuryBal = await provider.connection.getBalance(treasuryAddress);

    // Call verify_single
    await program.methods
      .verifySingle(
        Array.from(proofA),
        Array.from(proofB),
        Array.from(proofC),
        Array.from(nullifierHash),
        Array.from(attestationHash),
        Array.from(zkVdeProofHash),
        Array.from(ciphertextHash),
        timestamp
      )
      .accounts({
        registry: registryPda,
        shieldedPool: shieldedPoolPda,
        nullifierRecord: nullifierRecordPda,
        gateway: gateway.publicKey,
        treasury: treasuryAddress,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([gateway])
      .rpc();

    // Verify balances (Gateway gets 100K lamports, Treasury gets 50K lamports)
    const finalGatewayBal = await provider.connection.getBalance(gateway.publicKey);
    const finalTreasuryBal = await provider.connection.getBalance(treasuryAddress);

    assert.equal(finalGatewayBal - initialGatewayBal, 100000);
    assert.equal(finalTreasuryBal - initialTreasuryBal, 50000);

    // Verify registry stats
    const registryAccount = await program.account.protocolRegistry.fetch(registryPda);
    assert.equal(registryAccount.totalChirpsVerified.toNumber(), 1);
    assert.equal(registryAccount.totalFeesCollected.toNumber(), 150000);

    // Verify nullifier record state
    const nullifierAccount = await program.account.nullifierRecord.fetch(nullifierRecordPda);
    assert.deepEqual(nullifierAccount.nullifierHash, Array.from(nullifierHash));
  });

  it("Performs batch chirp verification (MODE B)", async () => {
    // Generate a new batch ID from registry
    const registryAccountBefore = await program.account.protocolRegistry.fetch(registryPda);
    const batchId = registryAccountBefore.nextBatchId;

    // Find PDA for the batch
    const batchIdBytes = batchId.toArrayLike(Buffer, "le", 8);
    const [batchPda, batchBump] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("zk-lorawan-batch"), gateway.publicKey.toBuffer(), batchIdBytes],
      program.programId
    );

    // Initialize batch
    await program.methods
      .initializeBatch()
      .accounts({
        batch: batchPda,
        registry: registryPda,
        gateway: gateway.publicKey,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([gateway])
      .rpc();

    const batchAccount = await program.account.batchAccumulator.fetch(batchPda);
    assert.ok(batchAccount.gateway.equals(gateway.publicKey));
    assert.equal(batchAccount.chirpCount, 0);
    assert.isFalse(batchAccount.isFinalized);

    // Add 3 chirps
    const chirp1Nullifier = crypto.randomBytes(32);
    const chirp1Attestation = crypto.randomBytes(32);
    const chirp1VdeProof = crypto.randomBytes(32);
    const chirp1Payload = crypto.randomBytes(32);

    const chirp2Nullifier = crypto.randomBytes(32);
    const chirp2Attestation = crypto.randomBytes(32);
    const chirp2VdeProof = crypto.randomBytes(32);
    const chirp2Payload = crypto.randomBytes(32);

    const chirp3Nullifier = crypto.randomBytes(32);
    const chirp3Attestation = crypto.randomBytes(32);
    const chirp3VdeProof = crypto.randomBytes(32);
    const chirp3Payload = crypto.randomBytes(32);

    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

    // Define mock proofs for mock-verifier feature bypass in batch tests
    const mockProofA = Buffer.alloc(64);
    mockProofA[0] = 0xDD;
    const mockProofB = Buffer.alloc(128);
    const mockProofC = Buffer.alloc(64);

    await program.methods
      .addChirp(
        Array.from(mockProofA),
        Array.from(mockProofB),
        Array.from(mockProofC),
        Array.from(chirp1Nullifier),
        Array.from(chirp1Attestation),
        Array.from(chirp1VdeProof),
        Array.from(chirp1Payload),
        timestamp
      )
      .accounts({
        batch: batchPda,
        gateway: gateway.publicKey,
      })
      .signers([gateway])
      .rpc();

    await program.methods
      .addChirp(
        Array.from(mockProofA),
        Array.from(mockProofB),
        Array.from(mockProofC),
        Array.from(chirp2Nullifier),
        Array.from(chirp2Attestation),
        Array.from(chirp2VdeProof),
        Array.from(chirp2Payload),
        timestamp
      )
      .accounts({
        batch: batchPda,
        gateway: gateway.publicKey,
      })
      .signers([gateway])
      .rpc();

    await program.methods
      .addChirp(
        Array.from(mockProofA),
        Array.from(mockProofB),
        Array.from(mockProofC),
        Array.from(chirp3Nullifier),
        Array.from(chirp3Attestation),
        Array.from(chirp3VdeProof),
        Array.from(chirp3Payload),
        timestamp
      )
      .accounts({
        batch: batchPda,
        gateway: gateway.publicKey,
      })
      .signers([gateway])
      .rpc();

    const batchAccountAfterAdd = await program.account.batchAccumulator.fetch(batchPda);
    assert.equal(batchAccountAfterAdd.chirpCount, 3);

    // Submit batch (Gateway gets 300K lamports, Treasury gets 150K lamports)
    const initialGatewayBal = await provider.connection.getBalance(gateway.publicKey);
    const initialTreasuryBal = await provider.connection.getBalance(treasuryAddress);

    const nullifiers = [chirp1Nullifier, chirp2Nullifier, chirp3Nullifier];
    const nullifierPdas = nullifiers.map((nullifier) => {
      const [pda] = anchor.web3.PublicKey.findProgramAddressSync(
        [Buffer.from("nullifier"), nullifier],
        program.programId
      );
      return { pubkey: pda, isWritable: true, isSigner: false };
    });

    await program.methods
      .submitBatch()
      .accounts({
        batch: batchPda,
        registry: registryPda,
        shieldedPool: shieldedPoolPda,
        gateway: gateway.publicKey,
        treasury: treasuryAddress,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([gateway])
      .remainingAccounts(nullifierPdas)
      .rpc();

    const finalGatewayBal = await provider.connection.getBalance(gateway.publicKey);
    const finalTreasuryBal = await provider.connection.getBalance(treasuryAddress);

    assert.equal(finalGatewayBal - initialGatewayBal, 300000);
    assert.equal(finalTreasuryBal - initialTreasuryBal, 150000);

    const batchAccountFinal = await program.account.batchAccumulator.fetch(batchPda);
    assert.isTrue(batchAccountFinal.isFinalized);
    assert.notDeepEqual(batchAccountFinal.merkleRoot, Array(32).fill(0));

    // Verify registry stats (total verified = 1 from single + 3 from batch = 4)
    const registryAccountAfter = await program.account.protocolRegistry.fetch(registryPda);
    assert.equal(registryAccountAfter.totalChirpsVerified.toNumber(), 4);
    assert.equal(registryAccountAfter.totalFeesCollected.toNumber(), 600000); // 150K + 450K

    // Test verify_chirp_inclusion
    const proof = buildMerkleProof(nullifiers, 0);
    await program.methods
      .verifyChirpInclusion(
        Array.from(chirp1Nullifier),
        proof.map(p => Array.from(p)),
        0
      )
      .accounts({
        batch: batchPda,
      })
      .rpc();
  });
});
