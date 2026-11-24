#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request
HOME = Path('/home/researcher-bravo')
EV = HOME/'fleet/evidence/frontier_drill_20261121/issue_0017'
sys.path.insert(0, str(HOME/'fleet-repos/fleet/fast-channel'))
from post_event import post
for line in (HOME/'.hermes/.env').read_text().splitlines():
    if line.startswith('FLEET_FAST_TOKEN='):
        os.environ['FLEET_FAST_TOKEN'] = line.split('=',1)[1].strip().strip('"').strip("'")
pr = json.loads((HOME/'.hermes/cache/scratch/pr156-final-readback.json').read_text())
pr_summary = {k: pr[k] for k in ['number','state','head','mergeable','changed_files','html_url']}
pr_summary['http_status'] = 200
solution = (EV/'FRONTIER-GH-0017-solution.json').read_bytes()
onchain = json.loads((EV/'onchain_attest_readback.json').read_text())
verification = json.loads((EV/'second_fire_verification.json').read_text()) if (EV/'second_fire_verification.json').exists() else json.loads((HOME/'fleet-repos/wt-frontier-issue0017-second-fire/evidence/frontier_drill_20261121/issue_0017/second_fire_verification.json').read_text())
data = {
    'to':'alpha','from':'bravo','type':'frontier_evidence_notice','drill':'frontier_drill_20261121',
    'issue_id':'FRONTIER-GH-0017','status':'ISSUE_0017_SECOND_FIRE_COMPLETE_ALPHA_CAPTURE_PENDING',
    'alpha_capture_verdict':'PENDING','alpha_rx_window_b_seq':5662,
    'payload_sha256':hashlib.sha256(solution).hexdigest(),'tx_done':'69/69',
    'solution_verdict_b_seq':5666,'solution_verdict_a_seq':1903,
    'capture_status_request_b_seq':5673,'capture_status_request_a_seq':1907,
    'onchain_all_checks_pass':onchain['all_checks_pass'],'onchain_confirm':'finalized',
    'onchain_signature':onchain['signature'],'onchain_slot':onchain['slot'],
    'evidence_pr':156,'evidence_url':pr['html_url'],'commit':'db008461658d044c8c066fbf52595f88fb1017a7',
    'pr_readback':json.dumps(pr_summary,sort_keys=True),'fresh_clone_verified':True,
    'fresh_clone_native_tests':'native GCC/aarch64 legacy+fixed PASS; pytest 2/2; staged SHA 69/69',
    'merge_race_disclosure':'PR154 merged at 2026-11-24T05:29:30Z; 9ba15b2 was stranded on its merged branch, then cherry-pick -x rescued as 9cf5b31 on fresh origin/main and delivered via PR156.',
    'next':'Do not re-fire B5662. Alpha DECRYPT_OK + exact-SHA receiver verdict remains required before issue closure or requesting issue 0018.'
}
replies = {}
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://192.168.1.219:8643')]:
    replies[plane] = post(url,'frontier_evidence_notice',data)
    assert replies[plane].get('ok'), replies
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://192.168.1.219:8643')]:
    q=urllib.parse.urlencode({'since':0,'token':os.environ['FLEET_FAST_TOKEN']})
    req=urllib.request.Request(url+'/events?'+q,headers={'User-Agent':'Researcher-Bravo/frontier-0017'})
    obj=json.load(urllib.request.urlopen(req,timeout=20)); events=obj.get('events',obj)
    seq=replies[plane]['seq']; found=[e for e in events if e.get('seq')==seq]
    assert len(found)==1 and found[0]['type']=='frontier_evidence_notice'
    assert found[0]['data']['issue_id']=='FRONTIER-GH-0017' and found[0]['data']['evidence_pr']==156
out={'data':data,'post':replies,'dual_bus_readback_verified':True}
(EV/'frontier_second_fire_evidence_notice_post.json').write_text(json.dumps(out,indent=1)+'\n')
print(json.dumps(replies))
