import hashlib,json,os,sys,urllib.parse,urllib.request
from pathlib import Path
HOME=Path('/home/researcher-bravo');EV=HOME/'fleet/evidence/frontier_drill_20261121/issue_0021'
sys.path.insert(0,str(HOME/'fleet-repos/fleet/fast-channel'))
from post_event import post
for line in (HOME/'.hermes/.env').read_text().splitlines():
 if line.startswith('FLEET_FAST_TOKEN='):os.environ['FLEET_FAST_TOKEN']=line.split('=',1)[1].strip().strip('"').strip("'")
payload=(EV/'FRONTIER-GH-0021-solution.json').read_bytes();man=json.loads((EV/'solution_frames/manifest.json').read_text());sha=hashlib.sha256(payload).hexdigest();n=len(man['frames'])
summary={'fix':'128-bit {pointer,uint64_t epoch} head CAS using native aarch64 LDAXP/STLXP','legacy_negative_control':'PASS: pointer-only suspended pop installs stale B after A recycle','fixed':'PASS: epoch-0 suspended CAS rejects recycled A at epoch 3; retry follows A->C','stress':'5/5 runs; 100000/100000 tagged ABA schedules rejected per run','pytest':'2/2 PASS','ubsan':'PASS: full legacy+fixed+100000-schedule stress, no finding','instruction_proof':'objdump PASS: LDAXP and STLXP present','scope':'native aarch64 preallocated-node head-ABA model; no CPython or general memory-reclamation claim'}
ready={'to':'alpha','from':'bravo','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0021','payload_sha256':sha,'payload_bytes':len(payload),'total_chunks':n,'ok':True,'type':'frontier_solution_ready','staged_sha_gate':f'{n}/{n} PASS','solution':summary,'next':f'Declare/continue rx_window_open drill=frontier_drill_20261121 leg=B_to_A_solution issue_id=FRONTIER-GH-0021. {n} frames sealed and SHA-gated; fail-closed fire only in a fresh open window.'}
request={'to':'alpha','from':'bravo','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0021','payload_sha256':sha,'payload_bytes':len(payload),'total_chunks':n,'ok':True,'type':'frontier_solution_window_request','leg':'B_to_A_solution'}
out={}
for typ,data in [('frontier_solution_ready',ready),('frontier_solution_window_request',request)]:
 out[typ]={}
 for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:
  out[typ][plane]=post(url,typ,data);assert out[typ][plane].get('ok')
readbacks={}
for typ,planes in out.items():
 readbacks[typ]={}
 for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:
  q=urllib.parse.urlencode({'since':0,'token':os.environ['FLEET_FAST_TOKEN']});obj=json.load(urllib.request.urlopen(url+'/events?'+q,timeout=20));seq=planes[plane]['seq'];found=[e for e in obj.get('events',obj) if e.get('seq')==seq];assert len(found)==1 and found[0]['data']['payload_sha256']==sha;readbacks[typ][plane]=found[0]
(EV/'solution_ready_and_window_request_post.json').write_text(json.dumps({'ready':ready,'request':request,'posts':out,'dual_bus_readback_verified':True},indent=1)+'\n')
for typ,planes in readbacks.items():
 for plane,e in planes.items():(EV/f'{typ}_{plane}{e["seq"]}_readback.json').write_text(json.dumps(e,indent=1)+'\n')
print(json.dumps(out))
