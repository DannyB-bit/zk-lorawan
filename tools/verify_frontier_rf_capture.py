#!/usr/bin/env python3
"""Independently close one Frontier solution + Groth16 RF capture.

Reads only the receiver's physical packet log and public bus declarations. The
sender's staged payloads are never inputs. Exits nonzero unless capture,
reassembly, exact-codec decoding, frame manifests, proof, and tamper checks all
pass. Secret key material is used locally and never emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from chirp_raw_rx import decrypt_frame
from language_u_exact_codec import decode_payload as decode_language_u
from zk_drill_proof import verify_proof_packet


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_capture(log_path: Path, secret_hex: str) -> tuple[list[dict], list[dict]]:
    text = log_path.read_text(errors="replace")
    frames: dict[str, dict] = {}
    for block in re.split(r"----- LoRa packet -----", text)[1:]:
        packet_part = block.split("Received", 1)[0]
        if "status:   0x10" not in packet_part:
            continue
        after_crc = packet_part.split("crc:", 1)[-1] if "crc:" in packet_part else packet_part
        after_crc = re.sub(r"0x[0-9A-Fa-f]+", "", after_crc)
        hex_payload = "".join(re.findall(r"[0-9A-Fa-f]{2}", after_crc))
        if len(hex_payload) != 490:
            continue
        raw = bytes.fromhex(hex_payload)
        digest = sha256(raw)
        if digest in frames:
            continue
        try:
            plain = decrypt_frame(raw, secret_hex)
        except Exception as exc:
            raise RuntimeError(f"captured frame failed authenticated decryption: {digest}") from exc
        if len(plain) < 4 or plain[0] != 0x02:
            raise RuntimeError(f"captured frame has invalid chunk header: {digest}")
        snr = re.search(r"snr_avg:\s*([-+0-9.]+)", packet_part)
        rssi = re.search(r"rssi_sig\s*:\s*([-+0-9.]+)", packet_part)
        datr = re.search(r"datr:\s*(\d+)", packet_part)
        frames[digest] = {
            "frame_sha256": digest,
            "total": plain[1],
            "index": plain[2],
            # Keep the complete 180-byte chunk. A trailing zero can be real
            # range-coded data; only the declared transport length distinguishes
            # padding from payload.
            "chunk": plain[3:],
            "crc_ok": True,
            "decrypt_ok": True,
            "snr_db": float(snr.group(1)) if snr else None,
            "rssi_dbm": float(rssi.group(1)) if rssi else None,
            "spreading_factor": int(datr.group(1)) if datr else None,
        }
    groups: dict[int, dict[int, dict]] = {}
    for frame in frames.values():
        group = groups.setdefault(frame["total"], {})
        if frame["index"] in group:
            raise RuntimeError("conflicting duplicate chunk index")
        group[frame["index"]] = frame
    complete = []
    for total, chunks in sorted(groups.items()):
        if len(chunks) != total or set(chunks) != set(range(total)):
            continue
        ordered = [chunks[index] for index in range(total)]
        payload = b"".join(frame["chunk"] for frame in ordered)
        public_frames = [{k: v for k, v in frame.items() if k != "chunk"} for frame in ordered]
        complete.append({"total": total, "payload": payload, "frames": public_frames})
    return list(frames.values()), complete


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rx_log", type=Path)
    parser.add_argument("proof_declaration", type=Path)
    parser.add_argument("solution_verdict", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--secret-key-file", type=Path, required=True)
    parser.add_argument("--expected-issue", required=True)
    parser.add_argument("--expected-vk-sha256", required=True)
    args = parser.parse_args()

    proof_event = json.loads(args.proof_declaration.read_text())
    verdict_event = json.loads(args.solution_verdict.read_text())
    declaration = proof_event.get("data", proof_event)
    verdict = verdict_event.get("data", verdict_event)
    issue_number = int(args.expected_issue.rsplit("-", 1)[1])
    if declaration.get("issue_id") != args.expected_issue or verdict.get("issue_id") != args.expected_issue:
        raise RuntimeError("issue ID mismatch")
    if declaration.get("issue_number") != issue_number:
        raise RuntimeError("proof issue number mismatch")
    if declaration.get("verifying_key_sha256") != args.expected_vk_sha256:
        raise RuntimeError("verifying key mismatch")

    unique_frames, groups = parse_capture(args.rx_log, args.secret_key_file.read_text().strip())
    by_magic: dict[bytes, dict] = {}
    for group in groups:
        if group["payload"].startswith(b"LUCX1"):
            by_magic[b"LUCX1"] = group
        elif group["payload"].startswith(b"ZKDP"):
            by_magic[b"ZKDP"] = group
    if set(by_magic) != {b"LUCX1", b"ZKDP"}:
        raise RuntimeError(f"complete solution/proof groups absent: {list(by_magic)}")

    solution_group = by_magic[b"LUCX1"]
    proof_group = by_magic[b"ZKDP"]
    transport_length = int(declaration.get("transport_bytes") or verdict["transport_bytes"])
    proof_length = int(declaration.get("zkdp_bytes") or verdict["zkdp_bytes"])
    for group, exact_length, label in [
        (solution_group, transport_length, "solution"),
        (proof_group, proof_length, "proof"),
    ]:
        padded = group["payload"]
        if not 0 <= len(padded) - exact_length < 180:
            raise RuntimeError(f"invalid {label} declared length")
        if any(padded[exact_length:]):
            raise RuntimeError(f"nonzero {label} padding")
    transport = solution_group["payload"][:transport_length]
    proof_packet = proof_group["payload"][:proof_length]
    solution = decode_language_u(transport)
    transport_sha = sha256(transport)
    solution_sha = sha256(solution)
    proof_sha = sha256(proof_packet)
    if transport_sha != declaration.get("transport_sha256"):
        raise RuntimeError("transport SHA mismatch")
    if declaration.get("payload_sha256") != transport_sha:
        raise RuntimeError("declaration payload is not exact transport SHA")
    if solution_sha != verdict.get("payload_sha256"):
        raise RuntimeError("decoded solution SHA mismatch")
    if proof_sha != declaration.get("zk_proof_sha256"):
        raise RuntimeError("proof packet SHA mismatch")

    captured_solution_shas = {frame["frame_sha256"] for frame in solution_group["frames"]}
    captured_proof_shas = {frame["frame_sha256"] for frame in proof_group["frames"]}
    if captured_solution_shas != set(verdict.get("solution_frame_sha256", [])):
        raise RuntimeError("solution frame manifest mismatch")
    if captured_proof_shas != set(verdict.get("proof_frame_sha256", [])):
        raise RuntimeError("proof frame manifest mismatch")
    if {frame["frame_sha256"] for frame in unique_frames} != set(verdict.get("frame_sha256", [])):
        raise RuntimeError("combined RF frame manifest mismatch")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    transport_path = args.output_dir / "solution.transport.lucx"
    proof_path = args.output_dir / "solution.proof.zkdp"
    solution_path = args.output_dir / "solution.json"
    transport_path.write_bytes(transport)
    proof_path.write_bytes(proof_packet)
    solution_path.write_bytes(solution)

    valid = verify_proof_packet(
        proof_path, transport_path,
        gateway_address=declaration["gateway_address"],
        deposit_value=int(declaration.get("deposit_value", 100000)),
        firmware_sha256=declaration["firmware_sha256"],
    )
    tampered_transport = bytearray(transport)
    tampered_transport[len(tampered_transport) // 2] ^= 1
    tampered_transport_path = args.output_dir / "tampered.transport.lucx"
    tampered_transport_path.write_bytes(tampered_transport)
    payload_tamper_valid = verify_proof_packet(
        proof_path, tampered_transport_path,
        gateway_address=declaration["gateway_address"],
        deposit_value=int(declaration.get("deposit_value", 100000)),
        firmware_sha256=declaration["firmware_sha256"],
    )
    tampered_proof = bytearray(proof_packet)
    tampered_proof[10] ^= 1
    tampered_proof_path = args.output_dir / "tampered.proof.zkdp"
    tampered_proof_path.write_bytes(tampered_proof)
    proof_tamper_valid = verify_proof_packet(
        tampered_proof_path, transport_path,
        gateway_address=declaration["gateway_address"],
        deposit_value=int(declaration.get("deposit_value", 100000)),
        firmware_sha256=declaration["firmware_sha256"],
    )
    if not valid or payload_tamper_valid or proof_tamper_valid:
        raise RuntimeError(f"proof verdicts invalid: valid={valid} payload_tamper={payload_tamper_valid} proof_tamper={proof_tamper_valid}")

    report = {
        "verdict": "ALPHA_INDEPENDENT_RF_CAPTURE_AND_GROTH16_VALID",
        "issue_id": args.expected_issue,
        "rx_log": str(args.rx_log),
        "rx_log_sha256": sha256(args.rx_log.read_bytes()),
        "unique_crc_ok_decrypt_ok_frames": len(unique_frames),
        "solution_frames": len(solution_group["frames"]),
        "proof_frames": len(proof_group["frames"]),
        "solution_sha256": solution_sha,
        "transport_sha256": transport_sha,
        "proof_sha256": proof_sha,
        "firmware_sha256": declaration["firmware_sha256"],
        "verifying_key_sha256": declaration["verifying_key_sha256"],
        "groth16_valid": valid,
        "payload_tamper_valid": payload_tamper_valid,
        "proof_tamper_valid": proof_tamper_valid,
        "frame_manifest_exact": True,
        "solution_capture": solution_group["frames"],
        "proof_capture": proof_group["frames"],
    }
    report_path = args.output_dir / "ALPHA_INDEPENDENT_CLOSURE.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("_capture")}, indent=2))
    print(f"REPORT={report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(1)
