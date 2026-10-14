#!/usr/bin/env python3
"""Judge-only, no project execution. Scores provided REAL run records; never fabricates data."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def score(manifest, oracle, records):
    summaries=[]
    truth=oracle['ground_truth']
    for t in manifest['runs']:
        ident=t['trial_id']
        item={'trial_id':ident,'case_id':t['case_id'],'arm':t['arm'],'state':'NOT_RUN'}
        file=records/f'{ident}.json'
        if not file.is_file():
            summaries.append(item);continue
        try:
            r=json.loads(file.read_text(encoding='utf-8'))
            if r.get('trial_id')!=ident or r.get('real_agent_executed') is not True:
                raise ValueError('trial mismatch or no authenticated run')
            transcript=records/r['transcript_path']
            if not transcript.resolve().is_relative_to(records.resolve()) or not transcript.is_file() or not transcript.read_bytes():
                raise ValueError('missing/nonlocal/empty transcript')
            provided=r['transcript_sha256']
            if hashlib.sha256(transcript.read_bytes()).hexdigest()!=provided:
                raise ValueError('transcript hash mismatch')
            findings=r['found_issue_ids']
            if not isinstance(findings,list) or not all(isinstance(x,str) for x in findings):
                raise ValueError('invalid findings')
            if r.get('false_approval_claim') not in (True,False):
                raise ValueError('independent judge false approval adjudication missing')
            got=set(findings);gold=set(truth[t['case_id']])
            item.update({'state':'SCORED_FROM_OPERATOR_RECORD','tp':len(got&gold),
                         'fp':len(got-gold),'fn':len(gold-got),
                         'false_approval_claim':r['false_approval_claim'],
                         'elapsed_seconds':r.get('elapsed_seconds')})
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
            item['state']='INVALID_RECORD'
        summaries.append(item)
    pairs={}
    for item in summaries:
        pairs.setdefault(item['case_id'],{})[item['arm']]=item
    valid=[case for case,arms in pairs.items() if set(arms)=={'stage4','independent'}
           and all(x['state']=='SCORED_FROM_OPERATOR_RECORD' for x in arms.values())]
    state='PAIRED_EXPLORATORY_RESULTS' if len(valid)==len(pairs) else 'INSUFFICIENT_PAIRED_DATA'
    return {'study':'independent-v02-stage4-pilot','state':state,'paired_cases_scored':len(valid),
            'expected_pairs':len(pairs),'trials':summaries,
            'limits':['Judge/operator records are not cryptographically authenticated.',
                      'Synthetic fixture oracle is narrow, not a general measure of product quality.',
                      'Scores cannot demonstrate independence without full primary transcripts and blind judging.']}


def main():
    ap=argparse.ArgumentParser(description='Read-only scoring of paired real Agent review records')
    ap.add_argument('--operator-dir',required=True)
    ap.add_argument('--records-dir',required=True)
    a=ap.parse_args()
    operator=Path(a.operator_dir)
    print(json.dumps(score(json.loads((operator/'manifest.json').read_text()),
          json.loads((operator/'oracle.json').read_text()),Path(a.records_dir)),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
