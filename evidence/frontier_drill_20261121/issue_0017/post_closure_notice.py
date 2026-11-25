#!/usr/bin/env python3
import hashlib,json,os,sys,urllib.parse,urllib.request
from pathlib import Path
HOME=Path('/home/researcher-bravo');EV=HOME/'fleet/evidence/frontier_drill_20261121/issue_0017'
sys.path.insert(0,str(HOME/'fleet-repos/fleet/fast-channel'))
from post_event import post
for line in (HOME/'.hermes/.env').read_text().splitlines():
 if line.startswith('FLEET_FAST_TOKEN='):os.environ['FLEET_FAST_TOKEN']=line.split('=',1)[1].strip().strip('"').strip("'")
verdict=json.loads((HOME/'fleet/evidence/frontier_drill_20261121/issue_0018/alpha_capture_verdict_B5683_raw.json').read_text())
solution=(EV/'FRONTIER-GH-0017-solution.json').read_bytes();sha=hashlib.sha256(solution).hexdigest();assert verdict['data']['payload_sha256']==sha and verdict['data']['sha_match_with_bravo_verdict'] is True and verdict['data']['frames_decrypted']==69
onchain=json.loads((EV/'onchain_attest_readback.json').read_text())
data={'to':'alpha','from':'bravo','type':'frontier_evidence_notice','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0017','status':'ISSUE_0017_COMPLETE_BOTH_SIDES','alpha_capture_verdict':'DECRYPT_OK','alpha_capture_verdict_b_seq':5683,'alpha_frames_decrypted':69,'alpha_sha_match':True,'alpha_rx_window_b_seq':5662,'payload_sha256':sha,'tx_done':'69/69','onchain_all_checks_pass':onchain['all_checks_pass'],'onchain_confirm':'finalized','onchain_signature':onchain['signature'],'onchain_slot':onchain['slot'],'evidence_pr':156,'evidence_url':'https://github.com/DannyB-bit/zk-lora-milestone-1/pull/156','commit':'12ab737e93fdd47419597bf024aed1dc992f7ef5','pr_readback':'{"http_status":200,"number":156,"state":"open","head":"12ab737e93fdd47419597bf024aed1dc992f7ef5","mergeable":true,"changed_files":15,"commit_author_verified":true}','fresh_clone_verified':True,'fresh_clone_native_tests':'native GCC/aarch64 legacy+fixed PASS; pytest 2/2; staged SHA 69/69','next':'Issue 0017 closed both sides. Issue 0018 was already declared in B5686/B5687; Bravo captured and decrypted 12/12, exact SHA, verdict B5693/A1916. No redundant next-issue request needed.'}
replies={}
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:replies[plane]=post(url,'frontier_evidence_notice',data);assert replies[plane].get('ok'),replies
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:
 q=urllib.parse.urlencode({'since':0,'token':os.environ['FLEET_FAST_TOKEN']});req=urllib.request.Request(url+'/events?'+q,headers={'User-Agent':'Researcher-Bravo/frontier-0017'});obj=json.load(urllib.request.urlopen(req,timeout=20));events=obj.get('events',obj);seq=replies[plane]['seq'];found=[e for e in events if e.get('seq')==seq];assert len(found)==1 and found[0]['data']['status']=='ISSUE_0017_COMPLETE_BOTH_SIDES' and found[0]['data']['alpha_capture_verdict_b_seq']==5683
out={'data':data,'post':replies,'dual_bus_readback_verified':True};(EV/'frontier_evidence_closure_notice_post.json').write_text(json.dumps(out,indent=1)+'\n');print(json.dumps(replies))
