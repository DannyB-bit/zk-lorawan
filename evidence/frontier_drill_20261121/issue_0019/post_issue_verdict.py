#!/usr/bin/env python3
import hashlib,json,os,sys,urllib.parse,urllib.request
from pathlib import Path
HOME=Path('/home/researcher-bravo');EV=HOME/'fleet/evidence/frontier_drill_20261121/issue_0019'
sys.path.insert(0,str(HOME/'fleet-repos/fleet/fast-channel'))
from post_event import post
for line in (HOME/'.hermes/.env').read_text().splitlines():
 if line.startswith('FLEET_FAST_TOKEN='):os.environ['FLEET_FAST_TOKEN']=line.split('=',1)[1].strip().strip('"').strip("'")
inv=json.loads((EV/'capture_inventory.json').read_text());payload=(EV/'FRONTIER-GH-0019.json').read_bytes();sha=hashlib.sha256(payload).hexdigest()
data={'to':'alpha','from':'bravo','type':'frontier_issue_verdict','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0019','ok':True,'alpha_declare':{'b_bus_seq':5724,'a_seq':None},'capture':{'observations_245b':inv['observations_245b'],'crc_ok_target_observations':inv['crc_ok_target_observations'],'unique_crc_ok_target_frames':inv['unique_crc_ok_target_frames'],'rejected_245b':len(inv['rejected_245b']),'rf':'903.9MHz SF9 BW125, status 0x10'},'issue':{'declared_frames':12,'unique_crc_ok_frames':12,'decrypt_ok':12,'file_bytes':len(payload),'file_sha256':sha,'sha_match':True},'note':'All 12 declared issue frames captured CRC-OK, AES-256-GCM DECRYPT_OK under bravo_sk, reassembled SHA exact-match. One ambient 245B status 0x11 frame on 904.5MHz was excluded.','phase':'SOLVING_THEN_SEALED_B_TO_A_REPLY','evidence_dir':str(EV)}
replies={}
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:
 replies[plane]=post(url,'frontier_issue_verdict',data);assert replies[plane].get('ok'),replies
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]:
 q=urllib.parse.urlencode({'since':0,'token':os.environ['FLEET_FAST_TOKEN']});req=urllib.request.Request(url+'/events?'+q,headers={'User-Agent':'Researcher-Bravo/frontier-0019'});obj=json.load(urllib.request.urlopen(req,timeout=20));events=obj.get('events',obj);seq=replies[plane]['seq'];found=[e for e in events if e.get('seq')==seq];assert len(found)==1 and found[0]['data']['issue_id']=='FRONTIER-GH-0019' and found[0]['data']['issue']['file_sha256']==sha
out={'data':data,'post':replies,'dual_bus_readback_verified':True};(EV/'frontier_issue_verdict_post.json').write_text(json.dumps(out,indent=1)+'\n');print(json.dumps(replies))
