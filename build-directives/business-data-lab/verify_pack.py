from pathlib import Path
import json,hashlib,re
from decimal import Decimal as D
root=Path(__file__).resolve().parent
manifest=json.loads((root/'LINE-COUNT-AND-HASHES.json').read_text())
assert len(manifest)==10
seen=set()
for item in manifest:
 p=root/item['path']; b=p.read_bytes(); s=b.decode(); ls=s.splitlines()
 assert len(ls)==item['lines'],p
 assert sum(bool(x.strip()) for x in ls)==item['nonblank_lines'],p
 assert item['nonblank_lines']>=2000,p
 assert hashlib.sha256(b).hexdigest()==item['sha256'],p
 ids=re.findall(r'^- \[(P\d{2}-[^\]]+)\]',s,re.M)
 assert len(ids)==len(set(ids)),('duplicate IDs',p)
 assert not seen.intersection(ids),p
 seen.update(ids)
 for section in ['Product mandate','known-answer fixture','Logical data model','metric contracts','workflow','Screen-by-screen','Adversarial','deliverables','work packages','portfolio acceptance','starting contracts']:
  assert section.lower() in s.lower(),(section,p)
 master=(root/'MASTER-DIRECTIVE.md').read_text()
 assert master in (root/'COMPLETE-COMBINED-DIRECTIVE.md').read_text()
 assert s in (root/'COMPLETE-COMBINED-DIRECTIVE.md').read_text()
# Independent arithmetic checks for all ten worked examples.
assert D(225)-D(140)-D(15)==D(70)
assert (D(225)-D(90))-(D(140)-D(60))-D(15)==D(40)
assert 24*2+18==66 and D('0.5')+D('0.5')==1
position=40+30-10; assert position==60
raw=max(120-position,50); assert ((raw+23)//24)*24==72
assert sum([0,10,20])/3==10 and 20+10==30
assert 6*20==120 and D(120)*D('1.10')==D(132)
assert D(30)/100-D(20)/100==D('.10')
assert (D('.30')-D('.20'))/D('.20')==D('.5')
assert D(95)/100==D('.95') and D(90)/95 != D(90)/100
assert 8+1+1==10
npv=-D(1000)+D(600)/D('1.1')+D(600)/(D('1.1')**2)
assert npv.quantize(D('.01'))==D('41.32')
assert sum([(D('.8')-1)**2,D('.6')**2,(D('.4')-1)**2,D('.1')**2])/4==D('.1925')
print(json.dumps({'status':'PASS','project_count':10,'minimum_nonblank_lines':min(x['nonblank_lines'] for x in manifest),'project_specification_lines':sum(x['lines'] for x in manifest),'requirement_ids':len(seen),'worked_fixture_arithmetic':'PASS'},indent=2))
