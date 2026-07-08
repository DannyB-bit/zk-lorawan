import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { assert } from "chai";
import * as crypto from "crypto";
import * as fs from "fs";
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

    const poolAccount = await program.account.shieldedEscrowPool.fetch(shieldedPoolPda) as any;
    assert.isTrue(poolAccount.totalBalance.toNumber() >= amount.toNumber());
    assert.deepEqual(poolAccount.merkleRoot, dummyLeafHash);
  });

  it("Performs single shielded chirp verification (MODE A)", async () => {
    const nullifierHash = Buffer.from("0e87a087cacb48b6a71b7294a792f1bc2b7d5a1c26068b6bdbfae7040135ac10", "hex");
    const attestationHash = Buffer.from("058bdd11761b4da4840596809626fac60c63b93e350833d98e54b20dbc59cc00", "hex");
    const zkVdeProofHash = Buffer.from("7dccb7b8d04f679b68efe81023118733aafa4d79b06b2784e69dd23206f6bd2a", "hex");
    const ciphertextHash = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");
    const timestamp = new anchor.BN(Math.floor(Date.now() / 1000));

    // Real, mathematically verified Groth16 proof coordinates
    const proofA = Buffer.from("2c30ce03531f45efcf0644e4faf5a72aa2f4bd6d5b46d0ef32db3960c89ae73202b55ea2408aa4536db4fa19902a3ef6baf923511f86b2338f3ff5bf9f96e2ab", "hex");
    const proofB = Buffer.from("030204527afed1183d759d41897faa48e72bfd72cea5c93e7bb4733126220cd4142c90bbab1c638ca064dcfdb550927941b85f9b0f6654bcc20126ab7ca13278095faa0544f10cb0190b7106f88774253f5b0a8381c55646940726e6ec486f7f04190fbfd32a91cf19db0f1425f97aed6b0f62d4cd563d60c92a90da3dd3acc9", "hex");
    const proofC = Buffer.from("0b3726f4e09f5d496be9229cedc33cddab4a97020016eec5b65843643febfecb2028447c13d606c2b5735f07d3e02feb4e145d77645c65b5114f2d3659e511f2", "hex");

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
    const proofA1 = Buffer.from("1b72721b8a7280f80ba37d195d96cdc05ca83f9b87727c4ea371102a6b0be8380023cd8fa1103882eabb917c72707f410af6b8c5e5bc44b9e9ccb2184a44314d", "hex");
    const proofB1 = Buffer.from("053926fd84cc33da661968ab06f2b92127c24f3694892b901e111aa857c2693f2bf894d4b28207444f4c91ad07831e86aa86058b0307b4fb700bce0f9809faad1a2547ff930bdb440318c097a6fea17548918770b2cc442ec449e50c4bb1609125c530608e99bb86016a0586182f65789cbc3374f2d049fde640e232d3d06b25", "hex");
    const proofC1 = Buffer.from("265d1ec46f9f11eb43f955eb94ebd37e36236efee2b0a871fd084c99e444f5200571f5ccb897918e5215b941fc3192c9390230436c4bb37d6181682bf9cdbf43", "hex");
    const chirp1Nullifier = Buffer.from("333d2924f9563337ce7aa25b5c25e315a510c0c510db6219b05fc7c396a7ee2c", "hex");
    const chirp1Attestation = Buffer.from("8b8cda973f4e99fb4729d7914dadd85533dea3d4ac45231ae2e72cc9c5c3ca17", "hex");
    const chirp1VdeProof = Buffer.from("79dc773d5b710f70fb4ce375853e25ad99d021bff5cd58d67c2e8f0032eee01f", "hex");
    const chirp1Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const proofA2 = Buffer.from("1444d0e900227be00abb528ee58029edd28ffc7890fa279bee4eac70b2ec415321830e1970b759f7760e2d9290e3981c661bb14e5fe1c4841ab0270b9b623595", "hex");
    const proofB2 = Buffer.from("3047a8523e48de601f73c465103c7cf6bcee10e2e635682ee763756018273cde019115b83249d28d5e246dd25aeb8638aed09ee040ecf90377f33d9a55326f81036962c65a81cb222d9b23e4a5280d320ad962b1956a1b6541b8fd59ea29acd80ab1da6886caa5de9717cb3268a44c2f6b9c1b63d1326c11a1fb76b11d64a89b", "hex");
    const proofC2 = Buffer.from("1bdc9de5c6fbcc16c66a955d6089a8e962979e22b748eb63f0eefcdddaaf8bb1087b69ce8f76bc817e643915f24095810c987be134a84fe5685e7ca55659dddd", "hex");
    const chirp2Nullifier = Buffer.from("f153d3fe8a4d1ac6196a9bd3d89c60b386f00e6919575f63e0bba958d35e5402", "hex");
    const chirp2Attestation = Buffer.from("482214239c1946ddc2d88e60457c0d46738ab0f43a302aa983f06ed4e1578b04", "hex");
    const chirp2VdeProof = Buffer.from("9c05c75001ab5fad4dadf4daa2a892bf8f4466fd77de76e3ccb626034d506504", "hex");
    const chirp2Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const proofA3 = Buffer.from("0f7fbfb33ce9448eb89b4188d8cb7529cae2ba82315f2a633315e24996e9830b29445760a774921dd089fe9bc786262717a94969e1a860d6dcb06d2fb76c777e", "hex");
    const proofB3 = Buffer.from("11a4c8297a38a0ce8c8aafafb0b8a5a19716ef820ef5d720a0fe699cf8e97f591a02ab8d8a0c070caefb25aacab0033e7b7c55baa799875fba77e38c2d6fb6b802a0a856d124d4d25531645bc8db1b091d5b79c178468bdb0a87685dae7ad6000f22d53787dcdd4e64df080a0eb5518211bd824cd12ce6f4c65eaeac1843614f", "hex");
    const proofC3 = Buffer.from("01dc3cf3c922e87c4c027df70550c4d108a9661e0026333c79788a82d6a180ef0021594dcd7bd1d195220052e77e7a82d67001873b54ab87bb24283a1fb372eb", "hex");
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
