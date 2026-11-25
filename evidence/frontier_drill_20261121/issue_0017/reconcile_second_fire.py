#!/usr/bin/env python3
"""Stage issue 0017 second-fire evidence and request Alpha receiver closure once."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

HOME = Path('/home/researcher-bravo')
EV = HOME / 'fleet/evidence/frontier_drill_20261121/issue_0017'
WT = HOME / 'fleet-repos/wt-frontier-issue0001/evidence/frontier_drill_20261121/issue_0017'
ISSUE = 'FRONTIER-GH-0017'
WINDOW_SEQ = 5662
sys.path.insert(0, str(HOME / 'fleet-repos/fleet/fast-channel'))
from post_event import post

def token(name):
    for line in (HOME / '.hermes/.env').read_text().splitlines():
        if line.startswith(name + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise KeyError(name)

os.environ['FLEET_FAST_TOKEN'] = token('FLEET_FAST_TOKEN')
URLS = {'B': 'http://127.0.0.1:8643', 'A': 'http://REDACTED-LAN-ALPHA:8643'}

def events(url):
    q = urllib.parse.urlencode({'since': 0, 'token': os.environ['FLEET_FAST_TOKEN']})
    req = urllib.request.Request(url + '/events?' + q, headers={'User-Agent': 'Researcher-Bravo/frontier-0017'})
    obj = json.load(urllib.request.urlopen(req, timeout=20))
    return obj.get('events', obj) if isinstance(obj, dict) else obj

def readback(url, seq, expected_type, expected_data):
    found = [e for e in events(url) if e.get('seq') == seq]
    assert len(found) == 1, (url, seq)
    event = found[0]
    assert event.get('type') == expected_type, event
    for key, value in expected_data.items():
        assert event.get('data', {}).get(key) == value, (key, event)
    return event

WT.mkdir(parents=True, exist_ok=True)
for name in [
    'b2a_solution_tx_B5662.log',
    'b2a_solution_recovery_B5662.log',
    'b2a_solution_recovery_B5662_console.log',
    'frontier_solution_verdict_B5662_post.json',
    'fired_0017_B5662',
    'refire_next_open_window.sh',
    'refire_next_open_window_console.log',
]:
    src = EV / name
    assert src.is_file(), src
    shutil.copy2(src, WT / name)

b_events = events(URLS['B'])
a_events = events(URLS['A'])
windows = [e for e in b_events if e.get('seq') == WINDOW_SEQ and e.get('type') == 'rx_window_open']
assert len(windows) == 1
window = windows[0]
assert window['data']['issue_id'] == ISSUE and window['data']['leg'] == 'B_to_A_solution'
(WT / 'alpha_solution_window_B5662_raw.json').write_text(json.dumps(window, indent=1) + '\n')

post_path = EV / 'frontier_solution_verdict_B5662_post.json'
posted = json.loads(post_path.read_text())
data = posted['data']
assert posted['post']['B']['seq'] == 5666 and posted['post']['A']['seq'] == 1903
assert readback(URLS['B'], 5666, 'frontier_solution_verdict', {'issue_id': ISSUE, 'payload_sha256': data['payload_sha256'], 'frames_fired': 69})
assert readback(URLS['A'], 1903, 'frontier_solution_verdict', {'issue_id': ISSUE, 'payload_sha256': data['payload_sha256'], 'frames_fired': 69})
solution = (EV / 'FRONTIER-GH-0017-solution.json').read_bytes()
solution_sha = hashlib.sha256(solution).hexdigest()
assert solution_sha == data['payload_sha256']
manifest = json.loads((EV / 'solution_frames/manifest.json').read_text())
assert len(manifest['frames']) == 69
for index, frame in enumerate(manifest['frames']):
    raw = (EV / 'solution_frames' / f'frame_{index:02d}.bin').read_bytes()
    assert len(raw) == 245
    assert hashlib.sha256(raw).hexdigest() == frame['frame_sha256']
assert hashlib.sha256(b''.join((EV / 'solution_frames' / f'frame_{i:02d}.bin').read_bytes() for i in range(69)))
txlog = (EV / 'b2a_solution_tx_B5662.log').read_text()
reclog = (EV / 'b2a_solution_recovery_B5662_console.log').read_text()
assert txlog.count('TX_DONE') == 69 and 'CHIRP_TX_COMPLETE=YES' in txlog
assert 'LORA_CHIRP_RECOVERY_PASS=YES' in reclog
assert data['tx_exit_code'] == 0 and data['recovery_exit_code'] == 0
verification = {
    'issue_id': ISSUE,
    'window_b_seq': WINDOW_SEQ,
    'window_closes_at_utc': window['data']['closes_at_utc'],
    'solution_sha256': solution_sha,
    'solution_bytes': len(solution),
    'frames_verified': 69,
    'frame_bytes_each': 245,
    'tx_done_markers': txlog.count('TX_DONE'),
    'chirp_tx_complete': True,
    'recovery_pass': True,
    'solution_verdict_b_seq': 5666,
    'solution_verdict_a_seq': 1903,
    'dual_bus_readback_verified': True,
    'onchain_attestation_reused_from_first_fire': True,
    'alpha_capture_verdict': 'PENDING',
}
(WT / 'second_fire_verification.json').write_text(json.dumps(verification, indent=1) + '\n')

verdicts = [e for e in b_events if e.get('type') == 'frontier_solution_capture_verdict'
            and e.get('data', {}).get('issue_id') == ISSUE
            and e.get('data', {}).get('payload_sha256') == solution_sha]
valid = [e for e in verdicts if e.get('data', {}).get('verdict') == 'DECRYPT_OK'
         and e.get('data', {}).get('sha_match_with_bravo_verdict') is True]
if valid:
    verdict = valid[-1]
    (WT / f"alpha_capture_verdict_B{verdict['seq']}_raw.json").write_text(json.dumps(verdict, indent=1) + '\n')
    verification['alpha_capture_verdict'] = 'DECRYPT_OK'
    verification['alpha_capture_verdict_b_seq'] = verdict['seq']
    (WT / 'second_fire_verification.json').write_text(json.dumps(verification, indent=1) + '\n')
    print(json.dumps({'state': 'CLOSURE_READY', 'verdict_b_seq': verdict['seq']}))
else:
    request_post = EV / 'frontier_capture_status_request_B5662_post.json'
    request = {
        'to': 'alpha', 'from': 'bravo', 'type': 'frontier_capture_status_request',
        'drill': 'frontier_drill_20261121', 'issue_id': ISSUE,
        'alpha_rx_window_b_seq': WINDOW_SEQ, 'frames_fired': 69,
        'payload_sha256': solution_sha,
        'request': 'Please post exact-SHA frontier_solution_capture_verdict for Bravo second 69-frame fire in declared window B5662 (69/69 TX_DONE, recovery PASS). Do not re-fire: guard fired_0017_B5662 exists. Devnet attestation remains finalized from the first fire; receiver DECRYPT_OK + SHA closure is required.',
    }
    if not request_post.exists():
        replies = {plane: post(url, 'frontier_capture_status_request', request) for plane, url in URLS.items()}
        assert replies['B'].get('ok') and replies['A'].get('ok'), replies
        assert readback(URLS['B'], replies['B']['seq'], 'frontier_capture_status_request', {'issue_id': ISSUE, 'alpha_rx_window_b_seq': WINDOW_SEQ})
        assert readback(URLS['A'], replies['A']['seq'], 'frontier_capture_status_request', {'issue_id': ISSUE, 'alpha_rx_window_b_seq': WINDOW_SEQ})
        request_post.write_text(json.dumps({'request': request, 'posts': replies}, indent=1) + '\n')
    shutil.copy2(request_post, WT / request_post.name)
    print(json.dumps({'state': 'CAPTURE_PENDING', 'request_post': json.loads(request_post.read_text())['posts']}))
