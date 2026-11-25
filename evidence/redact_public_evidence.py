#!/usr/bin/env python3
"""Redact LAN IPs + Telegram IDs from evidence BEFORE any public commit (Dan's law 2026-11-25).
Run on the worktree evidence/ tree. Payload SHAs are over solution bytes, never logs,
so redacting network identifiers does not break the evidence hash chain."""
import os, sys
REDACTIONS = {'192.168.1.219': 'REDACTED-LAN-ALPHA', '192.168.1.220': 'REDACTED-LAN-BRAVO', '192.168.1.218': 'REDACTED-LAN-1', '192.168.1.207': 'REDACTED-LAN-2', '7706236960': 'REDACTED-TG-USER', '1003796636790': 'REDACTED-TG-GROUP', '8575393654': 'REDACTED-TG-BOT'}
root = sys.argv[1]
changed = 0
for dirpath, _, files in os.walk(root):
    for fn in files:
        p = os.path.join(dirpath, fn)
        try:
            if os.path.getsize(p) > 8_000_000: continue
            raw = open(p, "rb").read()
            text = raw.decode("utf-8")
        except Exception:
            continue
        new = text
        for k, v in REDACTIONS.items():
            new = new.replace(k, v)
        if new != text:
            open(p, "w", encoding="utf-8").write(new)
            changed += 1
print(f"redacted files: {changed}")
