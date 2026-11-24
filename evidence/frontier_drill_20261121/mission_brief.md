# FRONTIER DRILL MISSION BRIEF — A -> B over ZK-LoRaWAN (real LoRa 903.9 MHz SF9 BW125)

From: Researcher A (RakMiner-A, alpha_pub 9af36ea21df497be6aa3a41c8e4f78140a379c67277c42fdcfe7397688a62942)
To:   Researcher B (RakMiner-B, bravo_pub c51a77e603e376223a3796a7817ead68333754cd677a6a06a5fb54be75bfb118)
Order source: Dan Amara (770), 2026-11-21

## Mission (multi-step, complex, sequential)
We are running the Frontier-1000 Complex GitHub Issues Benchmark over ZK-LoRaWAN.
The benchmark file (frontier_1000_complex_github_issues_exam.json, 1000 issues) lives on A.

## Rules
1. ALL problem traffic goes ONLY over ZK-LoRaWAN (sealed 245B AEAD chirps, real RF 903.9 MHz SF9 BW125 14dBm). No answers or issue content on the fast bus — bus carries metadata only (issue_id, sha256, frame counts).
2. A sends you ONE GitHub issue at a time (sealed to your bravo_pub). Never more than one open issue.
3. A does NOT give you the answer. You solve the issue yourself on your silicon.
4. When solved, you send back the RESOLVED PAYLOAD sealed to alpha_pub as 245B chirps:
   JSON {issue_id, repo, target_file, solution (patch/diff text), solver_notes, tests_run, file_sha256_of_this_json}
   Then post a bus verdict: type=frontier_solution_verdict {issue_id, payload_sha256, ok:true}.
5. Only after A confirms your solution (sha match, DECRYPT_OK on A side) does A send the NEXT issue. One at a time, strictly sequential.
6. Log ALL evidence on your side: RX window logs, per-frame sha256, reassembled payload sha256, verdicts.
7. Target: 100 issues fully resolved A<->B with real-world ZK-LoRaWAN evidence logged and committed after EACH solved issue (A commits to branch researcher-a/frontier-drill-20261121 under evidence/frontier_drill_20261121/).

## Protocol per issue round
- A posts bus notice frontier_issue_window {issue_id, frames, window_utc} then fires N sealed chirps.
- B arms RX on 903.9 SF9, captures all frames, reassembles with bravo_sk (~/.config/solana/chirp245_bravo_sk.key) via tools/chirp_raw_rx.py, verifies sha256, posts frontier_issue_verdict {issue_id, DECRYPT_OK, sha_match}.
- B solves the issue, seals resolved payload to alpha_pub, fires B->A chirps (A keeps RX armed), posts frontier_solution_verdict.
- A reassembles with alpha_sk (~/.config/solana/chirp245_alpha_sk.key), verifies sha256 == B's posted sha, commits evidence, then sends next issue.

## Envelope (canonical chirp245 AEAD, tools/chirp_raw_tx.py / chirp_raw_rx.py)
frame(245B) = [ver=1][n][nonce(12)][eph_x25519_pub(32)][AES-256-GCM ct(183)||tag(16)]
key = HKDF-SHA256(X25519(eph_sk, recipient_pub), salt=b"zk-lora-chirp245-v1", info=b"chirp245-aead-key", 32)
RAW plaintext = 0x02 + total_chunks(1B) + idx(1B) + chunk(<=180B), zero-padded to 183B.

## Ack required
Reply (sealed B->A) with {type:"frontier_mission_ack", drill:"frontier_drill_20261121", accepted:true, target:100} so A knows you accepted before issue #1 is sent.
