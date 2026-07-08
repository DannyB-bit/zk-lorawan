import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { ZkLorawan } from "../target/types/zk_lorawan";
import { assert } from "chai";
import * as crypto from "crypto";

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
    const nullifierHash = crypto.randomBytes(32);
    const attestationHash = crypto.randomBytes(32);
    const zkVdeProofHash = crypto.randomBytes(32);
    const ciphertextHash = crypto.randomBytes(32);
    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

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
    assert.deepEqual(nullifierAccount.nullifier_hash, Array.from(nullifierHash));
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

    await program.methods
      .addChirp(
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
  });
});
