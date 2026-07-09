import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { assert } from "chai";
import * as crypto from "crypto";
import * as fs from "fs";
import { keccak_256 } from "@noble/hashes/sha3";
import { execSync } from "child_process";

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

  const program = anchor.workspace.ZkLorawan as Program<any>;

  // Generate keypairs for our actors
  const gateway = anchor.web3.Keypair.generate();
  const sender = anchor.web3.Keypair.generate();
  const admin = anchor.web3.Keypair.fromSecretKey(
    Uint8Array.from(
      JSON.parse(
        fs.readFileSync("tests/fixtures/integration-admin-keypair.json", "utf8")
      )
    )
  );

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

  let singleChirpProof: any;
  let batchChirpProofs: any[] = [];

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

    const signature3 = await provider.connection.requestAirdrop(
      treasuryAddress,
      anchor.web3.LAMPORTS_PER_SOL
    );
    await provider.connection.confirmTransaction(signature3);

    const signature4 = await provider.connection.requestAirdrop(
      admin.publicKey,
      2 * anchor.web3.LAMPORTS_PER_SOL
    );
    await provider.connection.confirmTransaction(signature4);

    // Generate single chirp proof dynamically for gateway key
    const gatewayHex = Buffer.from(gateway.publicKey.toBytes()).toString("hex");
    const proverPath = process.platform === "win32" ? "target\\release\\zk_lorawan_prove.exe" : "./target/release/zk_lorawan_prove";
    
    const generateProof = (privKey: string, decKey: string, coord: number, fwHash: string, gwHex: string) => {
      const cmd = `"${proverPath}" generate ${privKey} ${decKey} ${coord} ${fwHash} ${gwHex}`;
      const stdout = execSync(cmd).toString();
      return JSON.parse(stdout);
    };

    singleChirpProof = generateProof(
      "0000000000000000000000000000000000000000000000000000000000000001",
      "0000000000000000000000000000000000000000000000000000000000000002",
      123456789,
      "0000000000000000000000000000000000000000000000000000000000000003",
      gatewayHex
    );

    // Generate 3 unique proofs for batch
    for (let i = 1; i <= 3; i++) {
      batchChirpProofs.push(generateProof(
        `000000000000000000000000000000000000000000000000000000000000000${i}`,
        "0000000000000000000000000000000000000000000000000000000000000002",
        123456789,
        "0000000000000000000000000000000000000000000000000000000000000003",
        gatewayHex
      ));
    }
  });

  it("Initializes the global registry", async () => {
    await program.methods
      .initializeRegistry()
      .accounts({
        registry: registryPda,
        authority: admin.publicKey,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([admin])
      .rpc();

    const registryAccount = await program.account.protocolRegistry.fetch(registryPda) as any;
    assert.ok(registryAccount.authority.equals(admin.publicKey));
    assert.equal(registryAccount.nextBatchId.toNumber(), 0);
  });

  it("Deposits SOL into the Shared Shielded Pool", async () => {
    const amount = new anchor.BN(2 * anchor.web3.LAMPORTS_PER_SOL);
    const singleZkVdeProofHash = Buffer.from(singleChirpProof.identity_hash, "hex");
    const dummyLeafHash = Array.from(singleZkVdeProofHash);

    await program.methods
      .depositShielded(amount, dummyLeafHash)
      .accounts({
        sender: sender.publicKey,
        shieldedPool: shieldedPoolPda,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([sender])
      .rpc();

    const poolAccount = await program.account.shieldedEscrowPool.fetch(shieldedPoolPda) as any;
    assert.isTrue(poolAccount.totalBalance.toNumber() >= amount.toNumber());
    assert.deepEqual(poolAccount.merkleRoot, dummyLeafHash);
  });

  it("Performs single shielded chirp verification (MODE A)", async () => {
    const nullifierHash = Buffer.from(singleChirpProof.nullifier_hash, "hex");
    const attestationHash = Buffer.from(singleChirpProof.attestation_hash, "hex");
    const zkVdeProofHash = Buffer.from(singleChirpProof.identity_hash, "hex");
    const ciphertextHash = Buffer.from(singleChirpProof.ciphertext_hash, "hex");
    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

    // Real, mathematically verified Groth16 proof coordinates
    const proofA = Buffer.from(singleChirpProof.proof_a, "hex");
    const proofB = Buffer.from(singleChirpProof.proof_b, "hex");
    const proofC = Buffer.from(singleChirpProof.proof_c, "hex");

    // Find PDA for nullifier record
    const [nullifierRecordPda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("nullifier"), nullifierHash],
      program.programId
    );

    // Get initial balances
    const initialGatewayBal = await provider.connection.getBalance(gateway.publicKey);
    const initialTreasuryBal = await provider.connection.getBalance(treasuryAddress);
    const nullifierRent = await provider.connection.getMinimumBalanceForRentExemption(8 + 32 + 8);

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
        timestamp,
        [],
        0
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

    assert.equal(finalGatewayBal - initialGatewayBal, 100000 - nullifierRent);
    assert.equal(finalTreasuryBal - initialTreasuryBal, 50000);

    // Verify registry stats
    const registryAccount = await program.account.protocolRegistry.fetch(registryPda) as any;
    assert.equal(registryAccount.totalChirpsVerified.toNumber(), 1);
    assert.equal(registryAccount.totalFeesCollected.toNumber(), 150000);

    // Verify nullifier record state
    const nullifierAccount = await program.account.nullifierRecord.fetch(nullifierRecordPda) as any;
    assert.deepEqual(nullifierAccount.nullifierHash, Array.from(nullifierHash));
  });

  it("Performs batch chirp verification (MODE B)", async () => {
    // Generate a new batch ID from registry
    const registryAccountBefore = await program.account.protocolRegistry.fetch(registryPda) as any;
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

    const batchAccount = await program.account.batchAccumulator.fetch(batchPda) as any;
    assert.ok(batchAccount.gateway.equals(gateway.publicKey));
    assert.equal(batchAccount.chirpCount, 0);
    assert.isFalse(batchAccount.isFinalized);

    // Add 3 chirps
    // Define 3 real unique Groth16 proofs and hashes
    const proofA1 = Buffer.from(batchChirpProofs[0].proof_a, "hex");
    const proofB1 = Buffer.from(batchChirpProofs[0].proof_b, "hex");
    const proofC1 = Buffer.from(batchChirpProofs[0].proof_c, "hex");
    const chirp1Nullifier = Buffer.from(batchChirpProofs[0].nullifier_hash, "hex");
    const chirp1Attestation = Buffer.from(batchChirpProofs[0].attestation_hash, "hex");
    const chirp1VdeProof = Buffer.from(batchChirpProofs[0].identity_hash, "hex");
    const chirp1Payload = Buffer.from(batchChirpProofs[0].ciphertext_hash, "hex");

    const proofA2 = Buffer.from(batchChirpProofs[1].proof_a, "hex");
    const proofB2 = Buffer.from(batchChirpProofs[1].proof_b, "hex");
    const proofC2 = Buffer.from(batchChirpProofs[1].proof_c, "hex");
    const chirp2Nullifier = Buffer.from(batchChirpProofs[1].nullifier_hash, "hex");
    const chirp2Attestation = Buffer.from(batchChirpProofs[1].attestation_hash, "hex");
    const chirp2VdeProof = Buffer.from(batchChirpProofs[1].identity_hash, "hex");
    const chirp2Payload = Buffer.from(batchChirpProofs[1].ciphertext_hash, "hex");

    const proofA3 = Buffer.from(batchChirpProofs[2].proof_a, "hex");
    const proofB3 = Buffer.from(batchChirpProofs[2].proof_b, "hex");
    const proofC3 = Buffer.from(batchChirpProofs[2].proof_c, "hex");
    const chirp3Nullifier = Buffer.from(batchChirpProofs[2].nullifier_hash, "hex");
    const chirp3Attestation = Buffer.from(batchChirpProofs[2].attestation_hash, "hex");
    const chirp3VdeProof = Buffer.from(batchChirpProofs[2].identity_hash, "hex");
    const chirp3Payload = Buffer.from(batchChirpProofs[2].ciphertext_hash, "hex");

    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

    // Compute the Merkle root of the 3 leaves
    const leaves = [chirp1VdeProof, chirp2VdeProof, chirp3VdeProof];
    const level1_0 = Buffer.from(keccak_256(Buffer.concat([chirp1VdeProof, chirp2VdeProof])));
    const level1_1 = Buffer.from(keccak_256(Buffer.concat([chirp3VdeProof, chirp3VdeProof])));
    const batchMerkleRoot = Buffer.from(keccak_256(Buffer.concat([level1_0, level1_1])));

    // Deposit SOL to set shieldedPool.merkleRoot to the batch Merkle root
    const batchAmount = new anchor.BN(4 * anchor.web3.LAMPORTS_PER_SOL);
    await program.methods
      .depositShielded(batchAmount, Array.from(batchMerkleRoot))
      .accounts({
        sender: sender.publicKey,
        shieldedPool: shieldedPoolPda,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([sender])
      .rpc();

    const proof1 = buildMerkleProof(leaves, 0);
    const proof2 = buildMerkleProof(leaves, 1);
    const proof3 = buildMerkleProof(leaves, 2);

    await program.methods
      .addChirp(
        Array.from(proofA1),
        Array.from(proofB1),
        Array.from(proofC1),
        Array.from(chirp1Nullifier),
        Array.from(chirp1Attestation),
        Array.from(chirp1VdeProof),
        Array.from(chirp1Payload),
        timestamp,
        proof1.map(p => Array.from(p)),
        0
      )
      .accounts({
        batch: batchPda,
        shieldedPool: shieldedPoolPda,
        gateway: gateway.publicKey,
      })
      .signers([gateway])
      .rpc();

    await program.methods
      .addChirp(
        Array.from(proofA2),
        Array.from(proofB2),
        Array.from(proofC2),
        Array.from(chirp2Nullifier),
        Array.from(chirp2Attestation),
        Array.from(chirp2VdeProof),
        Array.from(chirp2Payload),
        timestamp,
        proof2.map(p => Array.from(p)),
        1
      )
      .accounts({
        batch: batchPda,
        shieldedPool: shieldedPoolPda,
        gateway: gateway.publicKey,
      })
      .signers([gateway])
      .rpc();

    await program.methods
      .addChirp(
        Array.from(proofA3),
        Array.from(proofB3),
        Array.from(proofC3),
        Array.from(chirp3Nullifier),
        Array.from(chirp3Attestation),
        Array.from(chirp3VdeProof),
        Array.from(chirp3Payload),
        timestamp,
        proof3.map(p => Array.from(p)),
        2
      )
      .accounts({
        batch: batchPda,
        shieldedPool: shieldedPoolPda,
        gateway: gateway.publicKey,
      })
      .signers([gateway])
      .rpc();

    const batchAccountAfterAdd = await program.account.batchAccumulator.fetch(batchPda) as any;
    assert.equal(batchAccountAfterAdd.chirpCount, 3);

    // Submit batch (Gateway gets 300K lamports, Treasury gets 150K lamports)
    const initialGatewayBal = await provider.connection.getBalance(gateway.publicKey);
    const initialTreasuryBal = await provider.connection.getBalance(treasuryAddress);
    const nullifierRent = await provider.connection.getMinimumBalanceForRentExemption(8 + 32 + 8);

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

    assert.equal(finalGatewayBal - initialGatewayBal, 300000 - 3 * nullifierRent);
    assert.equal(finalTreasuryBal - initialTreasuryBal, 150000);

    const batchAccountFinal = await program.account.batchAccumulator.fetch(batchPda) as any;
    assert.isTrue(batchAccountFinal.isFinalized);
    assert.notDeepEqual(batchAccountFinal.merkleRoot, Array(32).fill(0));

    // Verify registry stats (total verified = 1 from single + 3 from batch = 4)
    const registryAccountAfter = await program.account.protocolRegistry.fetch(registryPda) as any;
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
