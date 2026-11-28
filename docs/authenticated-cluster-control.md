# Authenticated cluster control for ZK-LoRa

## Status

Implemented and tested:

- Ed25519-signed, domain-separated canonical JSON session manifests.
- Model SHA-256, worker Ed25519 identity, worker X25519 transport key, contiguous
  layer range, positive capacity weight (maximum 1e12), session ID, epoch,
  validity window and nonce are bound into every manifest.
- Trusted-coordinator, expiry, structural, model-hash and persistent replay gates.
- A 60-byte binary announcement committing to the complete signed envelope.

Not claimed or implemented here: tensor-RPC transport, a TLS/VPN tunnel,
distributed LLM inference, an inference ZK circuit, Solana settlement, or a
physical RF flight. Those require separate implementation and evidence.

## Trust and transport split

The complete manifest is fast-plane data. A coordinator sends it over an
authenticated fast channel. Each worker independently verifies the signature,
trusted coordinator, model hash, worker allocation, time window and epoch before
starting any native backend.

The LoRa announcement is only:

```text
offset  size  field
0       4     ASCII "ZKC1"
4       16    session ID
20      4     epoch, unsigned big-endian
24      4     expiry, Unix seconds, unsigned big-endian
28      32    SHA-256(MANIFEST_DOMAIN || canonical_json(signed_envelope))
```

It is a commitment, not a standalone authorization decision. The receiver must
obtain and verify the referenced manifest. Unknown or mismatched manifests fail
closed. Heavy activations and model tensors never belong in this RF message.

## Python API

```python
from cluster_control import (
    ReplayGuard, build_manifest, verify_manifest,
    pack_announcement, verify_announcement,
)

payload = verify_manifest(
    envelope,
    now=unix_seconds,
    trusted_coordinators={coordinator_ed25519_public_hex},
    expected_model_sha256=model_file_sha256,
    replay_guard=ReplayGuard("state/cluster-replay.json"),
)
announcement = pack_announcement(envelope)  # exactly 60 bytes
verify_announcement(announcement, envelope)
```

Private keys are raw 32-byte Ed25519 keys encoded as lowercase hex at the API
boundary. Callers must generate them with a CSPRNG and store them with owner-only
permissions. X25519 keys bind subsequent transport encryption to the admitted
worker identity; this module intentionally does not pretend to provide that
transport itself.

## Replay behavior

`ReplayGuard` permits one manifest per session epoch. A replay of the current
epoch and every older epoch are rejected. A strictly higher epoch advances the
fence. State updates use an inter-process file lock, an `fsync`ed temporary file
and atomic rename. The parent directory is `fsync`ed after the rename so the new
fence itself is durable across a crash on filesystems that honor these POSIX
durability calls. Corrupt state fails closed rather than being silently reset.

## Verification

Run from the repository root:

```bash
python3 -m unittest tests.test_cluster_control -v
```

The tests use real Ed25519 signatures and cover a valid manifest, model-hash
tampering, untrusted coordinator, expiry, non-contiguous layers, replay across a
restart, 60-byte announcement integrity, valid binary round trips and malformed
binary inputs. They are host-side protocol tests, not RF or inference benchmarks.
