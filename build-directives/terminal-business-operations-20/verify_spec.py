"""Validate the authored directive and worked arithmetic, not unbuilt applications."""
from pathlib import Path
from decimal import Decimal as D
from datetime import date,timedelta
import re,json,hashlib
r=Path(__file__).parent
s=(r/'MASTER-PROMPT.md').read_text()
projects=re.findall(r'<project id="(P\d+)" slug="([^"]+)" name="([^"]+)">(.*?)</project>',s,re.S)
assert [p[0] for p in projects]==[f'P{i}' for i in range(11,31)]
assert len({p[1] for p in projects})==20
for pid,slug,name,body in projects:
 for required in ['FIXTURE:', 'SCREENS:', 'ENTRY', 'ACCEPTANCE']:
  assert required in body,(pid,required)
 assert len(body.split())>=180,(pid,'insufficient specification')
for tag in ['mission','terminal_and_storage_contract','authorization_and_continuation','initial_discovery','model_body_architecture','visible_terminal_protocol','remote_bootstrap_and_ci','business_accuracy_contract','shipped_design_evidence','artifacts_and_portfolio','durable_state_and_token_economy','project_catalog','execution_algorithm','predeclared_acceptance_cases','official_reference_index','final_instruction']:
 assert s.count('<'+tag+'>')==1 and s.count('</'+tag+'>')==1,tag
checks={}
def check(id,condition):
 assert condition,id
 checks[id]='PASS'
check('P11',1000-100-300==600 and 600-200==400)
check('P12',(12-10)*100==200)
check('P13',date(2027,6,30)-timedelta(days=60)==date(2027,5,1) and date(2027,5,1)-timedelta(days=14)==date(2027,4,17) and date(2027,6,30)-timedelta(days=90)==date(2027,4,1))
check('P14',D(80)/100==D('.8') and D(50)/80==D('.625') and 15*20==300)
check('P15',D(600)+D(100)*D(2)/3+D(300)+D(100)/3==D(1000))
check('P16',160*D('.5')-100*D('.5')==30 and 1030-100-30==900)
check('P17',500+200-150==550 and 550-540==10 and max(2+3,4)==5)
check('P18',(10-6)*100==400 and (11-6)*90==450 and 11*90==990 and 400/(11-6)==80)
check('P19',140-100==40 and 40*30-500==700)
check('P20',max(9,11)>10 and D(2)/3>D('.6666'))
check('P21',80-10-5==65 and 95-25-10==60)
check('P22',800+250==1050 and 1100-1050==50 and 2+2>3)
check('P23',D(80)/100==D('.8') and D(95)/100==D('.95') and D(5)/100==D('.05'))
check('P24',D(50)/D('.25')==200 and 1000/100==10 and 800/50==16 and (D(16)-10)/10==D('.6'))
check('P25',(4+2)/2==3 and abs(4-2)==2 and 6-1==5)
check('P26',D(8)/10==D('.8'))
check('P27',date(2027,1,1)+timedelta(days=30)==date(2027,1,31))
check('P28',D('10.10')+D('20.20')+D('30.30')==D('60.60') and D('60.60')-(D('10.10')+D('20.20')+D('30.20'))==D('.10'))
check('P29',9*60+10+20+15==9*60+45 and 9*60+45>9*60+40)
check('P30',400-450==-50 and 400-500==-100 and D(400)/500==D('.8') and D(1000)/(D(400)/450)==1125)
manifest={'status':'PASS','project_count':len(projects),'word_count':len(s.split()),'line_count':len(s.splitlines()),'sha256':hashlib.sha256(s.encode()).hexdigest(),'fixture_arithmetic':checks,'scope':'Spec structure and worked examples only; applications are not built or validated.'}
(r/'VERIFICATION.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
