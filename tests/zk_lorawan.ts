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
    // Define 3 real unique Groth16 proofs and hashes
    const proofA1 = Buffer.from("26323ca8a4751c32c0b85a4f5c91799c5d7b1a1b863278a633d5d944b5c326f20b16c1906650d52f70618d7d64b6db3bad285c62969e5cffa3f2ce694c24b4a6", "hex");
    const proofB1 = Buffer.from("1b315483ab9f78a91f7e1eaa8bea1074339f1e6251657276665bd7f271ac6a920cca1d4ab9594af728d31d3428abb58bbbf24d73b85864d38225208e5e0f69f0a517289f398a937eebb534772afc22fa89a50bea9d2795336064c0189c4b66900a0398e178d63fe75367da7bdce8f5276ddb905080b42d0c051f5afcbb091aed", "hex");
    const proofC1 = Buffer.from("1c847e7b6803c870123860c7fee13233eb7e736989d49935730fe556577621a30a6a6e72bed2c418f3079f59d3a1087ae2b8bfac6e1442dd0061a5a7c488856c", "hex");
    const chirp1Nullifier = Buffer.from("333d2924f9563337ce7aa25b5c25e315a510c0c510db6219b05fc7c396a7ee2c", "hex");
    const chirp1Attestation = Buffer.from("8b8cda973f4e99fb4729d7914dadd85533dea3d4ac45231ae2e72cc9c5c3ca17", "hex");
    const chirp1VdeProof = Buffer.from("79dc773d5b710f70fb4ce375853e25ad99d021bff5cd58d67c2e8f0032eee01f", "hex");
    const chirp1Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const proofA2 = Buffer.from("2373ba50d483e8bbab9f65920b42e490d2043863e190396bc9002780d41e687e097c518327f494a43f2f1b283d1b89deebe954991a96ede1407fc820af6d6ecc", "hex");
    const proofB2 = Buffer.from("216a835c4114012d5c776e6b2276748b1e171e658287e03851375793840a08582578ffc1b7e0e8e4d718fe3a1f266166c8e511867173de2722371d0211884f970dea77423fbe2c52e14ad45de328653e732a98a39dafb960d4bd5488846a7c7223950e3d2996650df9015b0521a7aebd362a4965e3f7de063d33acbe98fe1aa5", "hex");
    const proofC2 = Buffer.from("0ee998adc65fc3b2392695753e7d189a01d18853a3f704811c572ed94e69d4b2abdfaac3a28d1d535925af68cbee09734d59937c2d8cd2dceceb24a29e604e8d", "hex");
    const chirp2Nullifier = Buffer.from("f153d3fe8a4d1ac6196a9bd3d89c60b386f00e6919575f63e0bba958d35e5402", "hex");
    const chirp2Attestation = Buffer.from("482214239c1946ddc2d88e60457c0d46738ab0f43a302aa983f06ed4e1578b04", "hex");
    const chirp2VdeProof = Buffer.from("9c05c75001ab5fad4dadf4daa2a892bf8f4466fd77de76e3ccb626034d506504", "hex");
    const chirp2Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const proofA3 = Buffer.from("27df7eb42d0ac1b6bb10f296be22a504d8cc3054f1a9933c04b6d6fff09074faabf7aeb0deac634b605ce252613113cd0a54ecbc81af4fcbcb1ffbe5ce1c3ae7", "hex");
    const proofB3 = Buffer.from("1cf1cac0fcb4ad43a1d6311844700bbfe9e581efe9ad1ec99b04964f35781a5c18c080d6c50f2a3a7faece6744f89905b466fde28987abc4a62661b96e268acb9b8bd1ca384a8c0c353bbff15ccfdd965658d2e90ecdf67bfee8697bc3fe218e09c385fa0e55c7bd8a4f15b23c3c6f57bea2e323575a90f0fa9b7d6dbdf70fdd", "hex");
    const proofC3 = Buffer.from("25e4c58a01164a0a9cea92de7172d9be150e485f479a9a70779735d2f4607c739ee55ad26c98b03e4b508cf42f2940c30f84fe834e488e1191504148ddaaef6e", "hex");
    const chirp3Nullifier = Buffer.from("a1bb0f97d5364577f3f7de2d7981281bec855a94975437fde8d5f6be0a8ef610", "hex");
    const chirp3Attestation = Buffer.from("9c02cf281a8259499690acee3b89e6e4ad53e2a728d491d48d0cd2d4760b7e17", "hex");
    const chirp3VdeProof = Buffer.from("1fac275faeecdbd9202414272ade21efc72098a70e07aef99ef3f9d638f12315", "hex");
    const chirp3Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

    await program.methods
      .addChirp(
        Array.from(proofA1),
        Array.from(proofB1),
        Array.from(proofC1),
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
        Array.from(proofA2),
        Array.from(proofB2),
        Array.from(proofC2),
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
        Array.from(proofA3),
        Array.from(proofB3),
        Array.from(proofC3),
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
