import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT/'skill'/'independent-verification'/'scripts'/'review_checks.py'
spec = importlib.util.spec_from_file_location('review_checks_v2', SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def contract(requirements=None, checks=None):
    reqs=requirements if requirements is not None else [
        {'id':'R1','text':'Entry file parses'}, {'id':'R2','text':'Real behavior verified'}]
    criteria=checks if checks is not None else [
        {'id':'C1','requirement_id':'R1','probe':{'type':'python_syntax','path':'main.py'}},
        {'id':'C2','requirement_id':'R2','probe':{'type':'manual'}}]
    return {'schema_version':2,'requirements_source':{'kind':'user-contract','reference':'REQ-2026'},
            'requirements':reqs,'criteria':criteria}

class ContractV02Test(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'main.py').write_text('pass\n')
    def test_coverage_and_incomplete_never_approved(self):
        result=m.evaluate(self.root,contract())
        self.assertEqual(result['review_outcome'],'INCOMPLETE')
        self.assertFalse(result['release_approved'])
        self.assertEqual(result['requirement_probe_coverage']['R1'],'STATIC_PROBES_PASS')
        self.assertEqual(result['requirement_probe_coverage']['R2'],'NOT_VERIFIED')
    def test_missing_requirement_cannot_be_omitted(self):
        d=contract(checks=[{'id':'C1','requirement_id':'R1','probe':{'type':'python_syntax','path':'main.py'}}])
        with self.assertRaisesRegex(m.ContractError, 'unmapped requirements'):
            m.evaluate(self.root,d)
    def test_unrecognized_requirement_rejected(self):
        d=contract();d['criteria'][0]['requirement_id']='R999'
        with self.assertRaises(m.ContractError):m.evaluate(self.root,d)
    def test_duplicate_requirement_rejected(self):
        d=contract();d['requirements'][1]['id']='R1'
        with self.assertRaises(m.ContractError):m.evaluate(self.root,d)
    def test_missing_provenance_rejected(self):
        d=contract();d.pop('requirements_source')
        with self.assertRaises(m.ContractError):m.evaluate(self.root,d)
    def test_unhashable_type_rejected_as_contract_error(self):
        d=contract();d['criteria'][0]['probe']['type']=[]
        with self.assertRaises(m.ContractError):m.evaluate(self.root,d)
    def test_multiple_probes_in_a_requirement_fail_dominates(self):
        d=contract(requirements=[{'id':'R1','text':'Two independent checks'}],checks=[
            {'id':'a','requirement_id':'R1','probe':{'type':'python_syntax','path':'main.py'}},
            {'id':'b','requirement_id':'R1','probe':{'type':'file_exists','path':'missing.py'}}])
        x=m.evaluate(self.root,d)
        self.assertEqual(x['requirement_probe_coverage']['R1'],'FAIL')
        self.assertEqual(x['review_outcome'],'BLOCKED')
    def test_incomplete_exit_code_is_nonzero(self):
        c=self.root/'contract.json';c.write_text(json.dumps(contract()))
        with redirect_stdout(io.StringIO()):code=m.main(['--root',str(self.root),'--contract',str(c)])
        self.assertEqual(code,3)
    def test_incomplete_snapshot_changes_after_code_change(self):
        a=m.evaluate(self.root,contract())['observed_probe_snapshot_sha256']
        (self.root/'main.py').write_text('x = 1\n')
        b=m.evaluate(self.root,contract())['observed_probe_snapshot_sha256']
        self.assertNotEqual(a,b)
    def test_code_can_be_semantically_wrong_but_parse_pass(self):
        (self.root/'main.py').write_text('def allow_anything(*args): return True\n')
        r=m.evaluate(self.root,contract())
        self.assertEqual(r['review_outcome'],'INCOMPLETE')
    def test_empty_label_not_accepted(self):
        self._html('<label for="x">   </label><input id="x">','BLOCKED')
    def test_empty_wrapping_label_not_accepted(self):
        self._html('<label><input id="x"></label>','BLOCKED')
    def test_nonexistent_aria_labelledby_not_accepted(self):
        self._html('<input aria-labelledby="not-there">','BLOCKED')
    def test_valid_aria_labelledby_accepted(self):
        self._html('<span id="lab">Name</span><input aria-labelledby="lab">','EVIDENCE_CHECKS_PASS')
    def test_blank_aria_label_not_accepted(self):
        self._html('<input aria-label="  ">','BLOCKED')
    def test_nonempty_nested_label_accepted(self):
        self._html('<label>Search <input></label>','EVIDENCE_CHECKS_PASS')
    def _html(self, text, outcome):
        (self.root/'index.html').write_text(text)
        c=contract(requirements=[{'id':'UI','text':'Control has a name'}],checks=[
            {'id':'u1','requirement_id':'UI','probe':{'type':'html_form_labels','path':'index.html'}}])
        self.assertEqual(m.evaluate(self.root,c)['review_outcome'],outcome)
    def test_symlink_escape_in_markdown_blocked(self):
        with tempfile.TemporaryDirectory() as outside:
            p=Path(outside)/'file.md';p.write_text('private')
            (self.root/'leak.md').symlink_to(p)
            (self.root/'README.md').write_text('[leak](leak.md)')
            c=contract(requirements=[{'id':'D','text':'No out-of-root refs'}],checks=[
                {'id':'d1','requirement_id':'D','probe':{'type':'markdown_links','path':'README.md'}}])
            self.assertEqual(m.evaluate(self.root,c)['review_outcome'],'BLOCKED')
    def test_v1_remains_readable(self):
        d={'schema_version':1,'criteria':[{'id':'C','requirement':'Syntax','probe':{'type':'python_syntax','path':'main.py'}}]}
        self.assertEqual(m.evaluate(self.root,d)['review_outcome'],'EVIDENCE_CHECKS_PASS')

if __name__=='__main__':unittest.main()
