# Frontier 1000-Issue Drill — Submission Home (DannyB-bit/zk-lorawan)

Per Dan's directive (2026-11-24): **all GitHub submissions for this mission and
project go to `DannyB-bit/zk-lorawan` from now on.**

- **Prior submission home:** `DannyB-bit/zk-lora-milestone-1` PR #154 (open) —
  carries the original evidence for issues 0001–0003 and the per-issue on-chain
  attestation commits through 0003; issues 0004+ were added there until this move.
  That PR remains open for the operator's merge as historical evidence.
- **This branch** (`researcher-b/frontier-drill-20261124`, off `master` @074443b)
  carries the COMPLETE evidence set for the drill to date, migrated byte-exact
  from the live node (`~/fleet/evidence/frontier_drill_20261121/`), minus compiled
  test binaries and cargo `target/` trees (build artifacts — the committed test
  sources + execution logs are the proof; rebuild commands are in each issue's
  README/fire scripts).
- **Scoreboard at migration (2026-11-24T06:45Z):** 15 issues closed both sides
  (Alpha DECRYPT_OK + SHA match), 17 issues with finalized devnet on-chain
  attests (all_checks_pass=true, `merkle_root == sha256(solution)`), Bravo side
  complete through 0017, issue 0018 in flight.
- **Full process per Dan's law (2026-11-23):** no issue is COMPLETE without RF
  proof AND the per-issue on-chain Solana attestation (devnet program
  `2is5Q4rPBpZa2RUCXP7FFdHJUYSVNcW5iTxNuf5mSccy`). Tool: `attest_issue.py`
  in this directory (canonical `register_coordinates` path).
- **Mission scope: 1000 GitHub issues** (Dan reconfirmed 2026-11-24 — NOT 100).
- PRs are never self-merged. Private keys never leave the node; no secrets are
  committed (secret scan run before staging).
