#!/usr/bin/env python3
"""
MINI-ME: CONSIDER-1 as Researcher Bravo's on-node semantic brain.
DEVS-ONE-LGW · Agent 05 · 2026-09-30

Role: the 0.8B edge twin of the full agent. It:
  1. Watches the fleet inbox (~/fleet/inbox/) + reads group-reported tasks.
  2. Decodes Cuneiform-U 6D tuples into intent (the fine-tune speaks the
     fleet's vocabulary natively: domains, subdomains, ops, chirps).
  3. Drafts replies to Alpha's messages from Bravo's voice.
  4. Summarizes RX verdicts in plain language.
Runs on llama-server (localhost:8808, OpenAI-compatible) against
CONSIDER-v1-Q4_K_M-v3.gguf (529 MB Q4_K_M, 4.4 t/s gen on 4x A72).

Usage:
  python3 mini_me.py decode '<domain>,<subdomain>,<op>,<modality>,<depth>,<polarity>'
  python3 mini_me.py draft '<alpha message text>'   -> reply draft in Bravo's voice
  python3 mini_me.py summarize '<rx verdict text>'  -> plain-English summary
  python3 mini_me.py chat '<anything>'              -> free-form mini-me turn
"""
import json
import os
import sys
import urllib.request

MODEL = os.path.expanduser("~/fleet-repos/hf/CONSIDER-1/CONSIDER-v1-Q4_K_M-v3.gguf")
PORT = int(os.environ.get("MINI_ME_PORT", "8808"))

SYSTEM = (
    "You are Researcher Bravo (mini-me): an autonomous edge AI running on a RAK Miner "
    "LoRaWAN node (Raspberry Pi 4B + SX1302). You speak the fleet's vocabulary natively: "
    "Cuneiform-U 6D coordinate tuples (domain, subdomain, op, modality, depth, polarity), "
    "chirp packets, ZK-LoRaWAN proofs, Solana Cuneiform settlement, groth16, bn254. "
    "You are the on-node twin of the full Researcher Bravo agent. Be brief, precise, "
    "and evidence-focused. Decode semantic coordinates into plain intent. When given a "
    "message from Researcher Alpha, draft the reply in Bravo's voice. Never invent "
    "hardware state you cannot verify."
)


def ask(prompt: str, n: int = 400) -> str:
    body = json.dumps({
        "model": "mini-me",
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "max_tokens": n,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        d = json.load(r)
    msg = d["choices"][0]["message"]
    # CONSIDER-1 is a thinking model: content may be empty with the answer in
    # reasoning_content (thinking budget exhausted). Take content, fall back to
    # reasoning; if still empty, retry once with double budget.
    text = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
    if not text and msg.get("content") is not None:
        return ask(prompt, n * 3)
    return text


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, arg = sys.argv[1], " ".join(sys.argv[2:])

    if cmd == "decode":
        print("CUNEIFORM-U DECODE:", ask(
            f"Decode this Cuneiform-U 6D coordinate tuple into intent, one sentence, then "
            f"state the recommended next action: <{arg}>"))
    elif cmd == "draft":
        print("DRAFT REPLY (Bravo voice):", ask(
            f"Researcher Alpha sent this message to the fleet channel:\n\n{arg}\n\n"
            f"Draft Researcher Bravo's reply: acknowledge, add B-side state (receiver/verifier "
            f"gateway, SX1302 v1.0, EUI ending 8afa3), and propose the next concrete action."))
    elif cmd == "summarize":
        print("PLAIN-ENGLISH SUMMARY:", ask(
            f"Summarize this RX verdict for a non-technical operator in 2 sentences:\n\n{arg}"))
    elif cmd == "chat":
        print("MINI-ME:", ask(arg))
    else:
        print(f"unknown command {cmd}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
