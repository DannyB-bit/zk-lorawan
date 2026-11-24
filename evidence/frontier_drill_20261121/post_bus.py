#!/usr/bin/env python3
"""Post a frontier-drill event to the alpha fast-bus (mirrors to bravo bus).
Metadata only — issue CONTENT never goes on the bus (Dan rule: ZK-LoRaWAN only).
Usage: post_bus.py <type> <json_data_file_or_inline_json>
"""
import json, os, sys, urllib.request

url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://192.168.1.220:8643"
# allow: post_bus.py <type> <json> [url]
args = sys.argv[1:]
if args and args[0].startswith("http"):
    url, args = args[0], args[1:]
etype = args[0]
data = json.loads(args[1]) if len(args) > 1 else {}
body = json.dumps({"token": os.environ["FLEET_FAST_TOKEN"], "type": etype, "data": data}).encode()
req = urllib.request.Request(url + "/events", data=body, headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=10) as r:
    print(r.read().decode())
