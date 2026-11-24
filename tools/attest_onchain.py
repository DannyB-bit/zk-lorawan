#!/usr/bin/env python3
"""Per-leg on-chain Solana attestation for the zk-LoRaWAN frontier drill (devnet).

Method (SPL Memo is NOT deployed on devnet): derived-key hash anchoring.
  artifact = canonical JSON bytes of the attestation object
  seed     = sha256(sha256(artifact))            (32B)
  address  = Keypair.from_seed(seed).pubkey()
  action   = fund `address` with 1,000,000 lamports (rent-exempt, 0-byte) from Alpha
Anyone holding the attestation JSON can re-derive the address and confirm the
funding signature+slot on any devnet RPC: proof the exact artifact existed,
byte-identical, before that block. No trust in the agent required.

Usage: attest_onchain.py <attestation.json> --yes
Prints JSON {attestation_sha256, derived_pubkey, signature, slot, explorer}.
"""
import sys, os, json, time, base64, hashlib, urllib.request
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.message import Message
from solders.transaction import VersionedTransaction
from solders.system_program import transfer, TransferParams

RPC = "https://api.devnet.solana.com"
FUNDER = os.path.expanduser("~/.config/solana/researcher-a-devnet.json")
LAMPORTS = 1_000_000  # rent-exempt minimum for a 0-byte system account

def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=25))
            if "error" in r:
                raise RuntimeError(str(r["error"]))
            return r["result"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))

def main():
    path = sys.argv[1]
    assert "--yes" in sys.argv, "refusing without --yes"
    att = json.load(open(path))
    artifact = json.dumps(att, sort_keys=True, separators=(",", ":")).encode()
    seed = hashlib.sha256(hashlib.sha256(artifact).digest()).digest()
    derived = Keypair.from_seed(seed)
    funder = Keypair.from_bytes(bytes(json.load(open(FUNDER))))

    bal = rpc("getBalance", [str(funder.pubkey())])["value"]
    if bal < LAMPORTS + 10_000:
        print(json.dumps({"error": "funder_low", "balance": bal}))
        sys.exit(2)

    # idempotent: if the derived address is already funded, recover the existing proof
    existing = rpc("getSignaturesForAddress", [str(derived.pubkey()), {"limit": 1}])
    if existing:
        sig = existing[0]["signature"]
        slot = existing[0]["slot"]
    else:
        bh = rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]
        ix = transfer(TransferParams(from_pubkey=funder.pubkey(), to_pubkey=derived.pubkey(), lamports=LAMPORTS))
        msg = Message.new_with_blockhash([ix], funder.pubkey(), Hash.from_string(bh["blockhash"]))
        tx = VersionedTransaction(msg, [funder])
        sig = rpc("sendTransaction", [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64"}])
        slot = None
        for _ in range(20):
            time.sleep(2)
            st = rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
            v = (st or {}).get("value", [None])[0]
            if v and v.get("confirmationStatus") in ("confirmed", "finalized"):
                if v.get("err"):
                    print(json.dumps({"error": "tx_failed", "sig": sig, "err": v["err"]}))
                    sys.exit(3)
                slot = v["slot"]
                break
        if slot is None:
            print(json.dumps({"error": "unconfirmed", "sig": sig}))
            sys.exit(4)

    print(json.dumps({
        "attestation_sha256": hashlib.sha256(artifact).hexdigest(),
        "derived_pubkey": str(derived.pubkey()),
        "signature": sig, "slot": slot,
        "funder": str(funder.pubkey()), "lamports": LAMPORTS, "cluster": "devnet",
        "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet"}))

if __name__ == "__main__":
    main()
