# Watermark: Pure Python Solana Private Key Printer
import os
import json

def b58encode(v):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(v, 'big')
    res = []
    while n > 0:
        n, r = divmod(n, 58)
        res.append(alphabet[r])
    for b in v:
        if b == 0:
            res.append(alphabet[0])
        else:
            break
    return "".join(reversed(res))

wallet_path = os.path.expanduser(r"C:\Users\DannyB\.config\solana\id.json")
if os.path.exists(wallet_path):
    try:
        with open(wallet_path, "r") as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) == 64:
                # In Solana, the private key for browser wallets is the base58 encoding of all 64 bytes
                key_bytes = bytes(data)
                privkey_b58 = b58encode(key_bytes)
                print("=" * 60)
                print("Your Base58 Private Key for Import:")
                print(privkey_b58)
                print("=" * 60)
            else:
                print(f"Error: Keypair file length is {len(data)}, expected 64.")
    except Exception as e:
        print(f"Error: {e}")
else:
    print(f"Error: File not found at {wallet_path}")
