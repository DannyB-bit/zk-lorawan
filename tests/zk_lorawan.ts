import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
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

  const program = anchor.workspace.ZkLorawan as Program<any>;

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

    const registryAccount = await program.account.protocolRegistry.fetch(registryPda) as any;
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
    const proofA = Buffer.from("2897f3a6e160e36a2a61701b38202851d3f3b7e5514891eab36e87631cb54049a57854ae98488963f463678c857d2bd344e2cc2f96579ba3532ec2276e572319", "hex");
    const proofB = Buffer.from("077689035cff51b9e9c5d2d808116c21a7c7048d243639761caa0a59d63f6eb7233557b6e690b33d3db688cb4920741e2bacedc34182bd47519e9a0ae18f45f717de1f363c9643abbcc14994e7d10a761e49a34c5d34bef51bc0bdbd7fcbd37b173fce1eaa88885e8392e720470e47f6871692816341ed4cc82a34572d96d0bc", "hex");
    const proofC = Buffer.from("2027b35d549dd4c47983589ea474db961f36210e5ef7f937310619eed2f9a0beaced32aa15bdf02328f84bfcdcd1d5dc4cd977215868b8dad8dd286644123a9f", "hex");

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
    const proofA1 = Buffer.from("133e15d4c64d432f09f2a979689818628c6729de70d1b50515f357084287101c136a4eb08074ca76daf6a4dcfedfbf3098f3ef4607df2432c0da16270fe1f690", "hex");
    const proofB1 = Buffer.from("260fd7028996abe6beb1443f1635e67b685e23ee911759a404a4f76ebd7281cc0460dad4631417cab497b3c7ccfb2f2ecaf311526a45e27ce275a37d34aae3eca1e8f82358bf84630e53082c2cb9e73efefa8226bb198be098ac98d925177d3312cb2dc99b0f07a3ce88b113435ff2ed32c8d88111a1f1b69f02d7660eaba6d0", "hex");
    const proofC1 = Buffer.from("12f5ea7753cbe3b1dc7bbdd8602a21efd4b50667ed9f5a1d14b0904b0bf86c0caebf219574b73d416e11118f7d8fa3075379618f2d21c709a6dc6e9966e8388e", "hex");
    const chirp1Nullifier = Buffer.from("333d2924f9563337ce7aa25b5c25e315a510c0c510db6219b05fc7c396a7ee2c", "hex");
    const chirp1Attestation = Buffer.from("8b8cda973f4e99fb4729d7914dadd85533dea3d4ac45231ae2e72cc9c5c3ca17", "hex");
    const chirp1VdeProof = Buffer.from("79dc773d5b710f70fb4ce375853e25ad99d021bff5cd58d67c2e8f0032eee01f", "hex");
    const chirp1Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const proofA2 = Buffer.from("0f95ebed4cdfc45bb780914c5d7bddc9ed649773eb80d8f01e2e2b6dc82a175c137d7a79df6c32c63fb7043c8fa7f50d816af1dad9bdf37b9653df0d8bb54cf9", "hex");
    const proofB2 = Buffer.from("105070c4e80547d34a74dabc85fc2854255f012e8bf6f00de23b91c88f45d0ed042a5a2abd159190e3d852470acd63491cc718edc4b9bf3e52b6bbb162be3ae0af3e844fd3798cfb0864fa1c7ee4077f4a5dda35f489e631ed2a9642e5bad94121ee65c2550f12368b620a7d354dd39f9802c278aba1ca73a0a2c17f8d01842c", "hex");
    const proofC2 = Buffer.from("2774decadedaa1bd6042b5e7bc057a03fab20a3ccddeb3a92b3ab57c72ae32f016e9c1a4a673564c667fc80306da398c2d6db1736a8d001ec5720a456624b8f6", "hex");
    const chirp2Nullifier = Buffer.from("f153d3fe8a4d1ac6196a9bd3d89c60b386f00e6919575f63e0bba958d35e5402", "hex");
    const chirp2Attestation = Buffer.from("482214239c1946ddc2d88e60457c0d46738ab0f43a302aa983f06ed4e1578b04", "hex");
    const chirp2VdeProof = Buffer.from("9c05c75001ab5fad4dadf4daa2a892bf8f4466fd77de76e3ccb626034d506504", "hex");
    const chirp2Payload = Buffer.from("77bd13e5607e8bd91c59bc51c1a17d9c65ac3f29d5df56276cf9eb9d3ef30122", "hex");

    const proofA3 = Buffer.from("1b6e34a38006877f1452d4253f3edb08a17b793ca98130ff939dd6619f718796abae33f6c39061fa8fb87d5601dee591435d83873b02259bb4894c0a33cfc5d3", "hex");
    const proofB3 = Buffer.from("12db7d2863bdd6c8eee194a6db8b539f2c8e5bac8a942726512afa23e8bbdc1d13e9f6e52abd3fcfb77045086061747b037b3d0d30ce2d4715ea935c23139c9b0d06e4cb77d642fa4eedd98c0ceedf3c81bc01949dd2b6366eb239dcac53e4d119c814bfc7a94c5a831332ffa0c230c6a3b28c3d632e7677d558ab155e5e4e07", "hex");
    const proofC3 = Buffer.from("05098ae44de02a789b4827d11820bbf6c33c5865398264716cd145006e0a77930443aaffd470b7cbcf7afe35d538504e309b2b77b70293843423b978d79f4266", "hex");
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
