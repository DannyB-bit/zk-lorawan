import hashlib,json,os,sys
from pathlib import Path
HOME=Path('/home/researcher-bravo');EV=HOME/'fleet/evidence/frontier_drill_20261121/issue_0019'
sys.path.insert(0,str(HOME/'fleet-repos/fleet/fast-channel'))
from post_event import post
for line in (HOME/'.hermes/.env').read_text().splitlines():
 if line.startswith('FLEET_FAST_TOKEN='):os.environ['FLEET_FAST_TOKEN']=line.split('=',1)[1].strip().strip('"').strip("'")
payload=(EV/'FRONTIER-GH-0019-solution.json').read_bytes();man=json.loads((EV/'solution_frames/manifest.json').read_text());sha=hashlib.sha256(payload).hexdigest();n=len(man['frames'])
ready={'to':'alpha','from':'bravo','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0019','payload_sha256':sha,'payload_bytes':len(payload),'total_chunks':n,'ok':True,'type':'frontier_solution_ready','staged_sha_gate':f'{n}/{n} PASS','solution':{'fix':'head_mutex validates interpreter membership before atomic daemon-ref acquisition; deallocation waits for refcount zero','legacy_negative_control':'PASS: old_refs=0 invalid acquire after retirement reproduced','fixed_stress':'PASS: 2000 concurrent allocate/race/free iterations; 2000 frees; acquire+reject orderings','pytest':'2/2 PASS','ubsan':'PASS: same 2000-iteration stress, no finding','asan':'ENVIRONMENT_BLOCKED at allocator initialization; disclosed, not claimed','scope':'native aarch64 pthread regression model, not an upstream CPython/Linux patch'},'next':'Declare/continue rx_window_open drill=frontier_drill_20261121 leg=B_to_A_solution issue_id=FRONTIER-GH-0019. 44 frames sealed and SHA-gated; fail-closed fire only in a fresh open window.'}
request={'to':'alpha','from':'bravo','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0019','payload_sha256':sha,'payload_bytes':len(payload),'total_chunks':n,'ok':True,'type':'frontier_solution_window_request','leg':'B_to_A_solution'}
out={}
for typ,data in [('frontier_solution_ready',ready),('frontier_solution_window_request',request)]:
 out[typ]={}
 for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:out[typ][plane]=post(url,typ,data);assert out[typ][plane].get('ok')
(EV/'solution_ready_and_window_request_post.json').write_text(json.dumps({'ready':ready,'request':request,'posts':out},indent=1));print(json.dumps(out))
