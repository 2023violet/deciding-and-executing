#!/usr/bin/env python3
"""Build and verify the v0.2 candidate. No deletes, no network, no Git mutation."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

BASE=Path(__file__).resolve().parent
OUT=Path('/mnt/data')
SKILL=BASE/'skill'/'independent-verification'
SKILL_ZIP=OUT/'independent-verification-v0.2.0-CANDIDATE.skill'
SOURCE_ZIP=OUT/'Independent-Verification-v0.2.0-CANDIDATE.zip'
FULL_ZIP=OUT/'Deciding-Executing-Independent-Verification-v0.2-Complete-Candidate.zip'
CHECKSUMS=OUT/'Deciding-Executing-Independent-Verification-v0.2-Checksums.json'
INCLUSIONS={
    'core/deciding-and-executing-v4.1.0-CANDIDATE.skill':OUT/'deciding-and-executing-v4.1.0-CANDIDATE.skill',
    'core/closing-out-v2.0.1-R123.skill':OUT/'closing-out-v2.0.1-R123.skill',
    'core/Deciding-Executing-R123-Complete-Candidate.BASELINE.zip':OUT/'Deciding-Executing-R123-Complete-Candidate.zip',
    'r1-frozen/Deciding-Executing-R1-Evaluation-Kit.zip':OUT/'Deciding-Executing-R1-Evaluation-Kit.zip',
    'r1-frozen/Deciding-Executing-R1-Prepared-Trials.zip':OUT/'Deciding-Executing-R1-Prepared-Trials.zip',
}

def eligible(p):
    return p.is_file() and not any(x in ('__pycache__','.pytest_cache','.git') for x in p.parts) and p.suffix!='.pyc'

def source_files():
    return sorted(p for p in BASE.rglob('*') if eligible(p))

def make_zip(path,entries):
    # Each filename is encoded UTF-8 by zipfile when needed; no external compression utility.
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for arcname,p in entries:
            z.write(p,arcname=arcname)
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise RuntimeError('ZIP CRC mismatch')
        actual=set(z.namelist()); expected={arc for arc,_ in entries}
        if actual!=expected:raise RuntimeError('ZIP entries mismatch')
        for arc,p in entries:
            if z.read(arc)!=p.read_bytes():raise RuntimeError('ZIP bytes mismatch: '+arc)
    return len(entries)

if __name__=='__main__':
    for name,p in INCLUSIONS.items():
        if not p.is_file():raise FileNotFoundError(str(p))
    source=source_files()
    a=make_zip(SKILL_ZIP,[('independent-verification/'+p.relative_to(SKILL).as_posix(),p) for p in source if p.is_relative_to(SKILL)])
    b=make_zip(SOURCE_ZIP,[('independent-verification-v0.2.0/'+p.relative_to(BASE).as_posix(),p) for p in source]+[
        ('independent-verification-v0.2.0/install/'+SKILL_ZIP.name,SKILL_ZIP)])
    c=make_zip(FULL_ZIP,[('delivery/'+n,p) for n,p in INCLUSIONS.items()]+[
        ('delivery/new/'+SKILL_ZIP.name,SKILL_ZIP),('delivery/new/'+SOURCE_ZIP.name,SOURCE_ZIP),
        ('delivery/new/ENGINEERING_REPORT.md',BASE/'PILOT_ENGINEERING_REPORT.md')])
    checks={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in (SKILL_ZIP,SOURCE_ZIP,FULL_ZIP)}
    CHECKSUMS.write_text(json.dumps({'status':'CANDIDATE_NOT_PUBLIC_RELEASE','checksums':checks,'files':{'skill':a,'source':b,'full':c}},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'ok':True,'artifacts':checks,'entries':{'skill':a,'source':b,'full':c}},ensure_ascii=False,indent=2))
