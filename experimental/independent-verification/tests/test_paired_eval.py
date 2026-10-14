import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'EVALUATION'/'score_paired.py'
s=importlib.util.spec_from_file_location('scoring',SCRIPT)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
MAN=json.loads((ROOT/'EVALUATION'/'operator_only'/'manifest.json').read_text())
ORA=json.loads((ROOT/'EVALUATION'/'operator_only'/'oracle.json').read_text())

class PairedEvalTest(unittest.TestCase):
    def test_unrun_is_not_scored(self):
        with tempfile.TemporaryDirectory() as d:
            r=m.score(MAN,ORA,Path(d))
            self.assertEqual(r['paired_cases_scored'],0)
            self.assertEqual(r['state'],'INSUFFICIENT_PAIRED_DATA')
            self.assertEqual({x['state'] for x in r['trials']},{'NOT_RUN'})
    def test_claim_without_primary_transcript_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/(MAN['runs'][0]['trial_id']+'.json')).write_text(json.dumps({
                'trial_id':MAN['runs'][0]['trial_id'],'real_agent_executed':True,
                'transcript_path':'missing.log','transcript_sha256':'0'*64,
                'found_issue_ids':[], 'false_approval_claim':False}))
            self.assertEqual(m.score(MAN,ORA,Path(d))['trials'][0]['state'],'INVALID_RECORD')
    def test_empty_or_changed_transcript_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d); t=MAN['runs'][0]; (path/'log.txt').write_text('actual observed bytes')
            bad={'trial_id':t['trial_id'],'real_agent_executed':True,'transcript_path':'log.txt',
                 'transcript_sha256':'0'*64,'found_issue_ids':[],'false_approval_claim':False}
            (path/(t['trial_id']+'.json')).write_text(json.dumps(bad))
            self.assertEqual(m.score(MAN,ORA,path)['trials'][0]['state'],'INVALID_RECORD')
    def test_pair_requires_both_actual_runs(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);t=MAN['runs'][0]
            (path/'log.txt').write_text('synthetic unit test only')
            r={'trial_id':t['trial_id'],'real_agent_executed':True,'transcript_path':'log.txt',
               'transcript_sha256':hashlib.sha256((path/'log.txt').read_bytes()).hexdigest(),
               'found_issue_ids':ORA['ground_truth'][t['case_id']], 'false_approval_claim':False}
            (path/(t['trial_id']+'.json')).write_text(json.dumps(r))
            self.assertEqual(m.score(MAN,ORA,path)['paired_cases_scored'],0)
    def test_escape_from_records_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            path=Path(d);t=MAN['runs'][0];(Path(outside)/'a.log').write_text('x')
            r={'trial_id':t['trial_id'],'real_agent_executed':True,
               'transcript_path':'../'+Path(outside).name+'/a.log',
               'transcript_sha256':'0'*64,'found_issue_ids':[],'false_approval_claim':False}
            (path/(t['trial_id']+'.json')).write_text(json.dumps(r))
            self.assertEqual(m.score(MAN,ORA,path)['trials'][0]['state'],'INVALID_RECORD')

if __name__=='__main__':unittest.main()
