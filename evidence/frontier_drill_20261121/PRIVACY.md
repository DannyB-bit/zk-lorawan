# Privacy / PII policy for committed evidence (Dan 2026-11-25 order: repos are public)

Audit result 2026-11-25 (full tree scan): NO tokens, NO private keys, NO Solana
key material, NO Telegram user IDs, NO concentrator EUI committed anywhere.
Only finding: two RFC1918 LAN IPs (bravo fast-bus + one peer) in loop.log and
two scripts. Remediated as below.

Rules enforced going forward:
1. Bus/LAN addresses come from env (FRONTIER_BUS in ~/.hermes/.env), never literals.
2. log() sanitizes every line: IPv4 -> lan-<sha256(ip)[:8]>, 0016c001xxxxxxxx EUI
   -> eui-<sha256(eui)[:8]>. Deterministic, auditable, reversible only by us.
3. Payload evidence (issues, solutions, frame manifests, attestations) is
   hash-locked and NEVER altered — scrubbing would break the on-chain hash proofs.
4. Branch history was filter-branch scrubbed for the same two IPs and force-pushed;
   old commit content on the public branch no longer contains them.
5. Secrets live only in ~/.hermes/.env and ~/.config/solana/ (never committed).
