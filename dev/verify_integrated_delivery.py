#!/usr/bin/env python3
"""Read-only structural and byte-integrity verification for the unified repository."""
from pathlib import Path
import hashlib,json,sys,zipfile
BASE=Path(__file__).resolve().parents[1]
SKILLS={
 'deciding-and-executing':('skills/deciding-and-executing','dist/deciding-and-executing.skill'),
 'closing-out':('skills/closing-out','dist/closing-out.skill'),
 'independent-verification':('experimental/independent-verification/skill/independent-verification','dist/experimental/independent-verification-v0.2.0-CANDIDATE.skill'),
}
def check():
 checks=[]
 for name,(folder,archive) in SKILLS.items():
  src=BASE/folder;zpath=BASE/archive
  if not src.is_dir() or not zpath.is_file(): raise RuntimeError(f'Missing {name} source/archive')
  fs={p.relative_to(src).as_posix():p.read_bytes() for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
  with zipfile.ZipFile(zpath) as z:
   if z.testzip():raise RuntimeError('Corrupted skill '+name)
   files={n[len(name)+1:]:z.read(n) for n in z.namelist() if n.startswith(name+'/') and not n.endswith('/')}
  if fs!=files:
   missing=set(fs)^set(files)
   wrong=[n for n in fs.keys()&files.keys() if fs[n]!=files[n]]
   raise RuntimeError(f'{name}: mismatched files={sorted(missing)}, bytes={wrong}')
  checks.append({'skill':name,'source_files':len(fs),'archive_match':True})
 if (BASE/'experimental/independent-verification/EVALUATION/operator_only').exists():
  raise RuntimeError('Operator-private gold mistakenly inside GitHub-ready repository')
 return {'ok':True,'skills':checks,'operator_gold_in_repo':False,'scope':'byte and structure only; not Agent behavior'}
if __name__=='__main__':
 try:
  print(json.dumps(check(),ensure_ascii=False,indent=2));sys.exit(0)
 except Exception as e:
  print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
