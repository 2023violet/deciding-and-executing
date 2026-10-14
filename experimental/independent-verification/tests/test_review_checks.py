import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'skill'/'independent-verification'/'scripts'/'review_checks.py'
spec=importlib.util.spec_from_file_location('review_checks', SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class IndependentChecksTest(unittest.TestCase):
    def spec(self, t, path=None, **kwargs):
        probe={'type':t};
        if path:probe['path']=path
        probe.update(kwargs)
        return {'schema_version':1,'criteria':[{'id':'C1','requirement':'test','probe':probe}]}
    def test_case_results(self):
        expected={'code':'INCOMPLETE','ui':'BLOCKED','docs':'BLOCKED'}
        for name,verdict in expected.items():
            with self.subTest(name=name):
                root=ROOT/'cases'/name
                self.assertEqual(m.evaluate(root,self.load(root))['review_outcome'],verdict)
    def load(self,root):
        return json.loads((root/'contract.json').read_text())
    def test_python_syntax_not_behavioral_proof(self):
        d=ROOT/'cases'/'code'; v=m.evaluate(d,self.spec('python_syntax','security.py'))
        self.assertEqual(v['review_outcome'],'EVIDENCE_CHECKS_PASS')
        self.assertFalse(v['release_approved'])
        self.assertIn('NOT verified',v['findings'][0]['detail'])
    def test_markdown_link_fixed(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t);(root/'docs').mkdir();(root/'docs'/'usage.md').write_text('# usage')
            (root/'README.md').write_text('[x](docs/usage.md)')
            self.assertEqual(m.evaluate(root,self.spec('markdown_links','README.md'))['review_outcome'],'EVIDENCE_CHECKS_PASS')
    def test_html_label_detected_and_fixed(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); (root/'index.html').write_text('<label for="x">Email</label><input id="x">')
            self.assertEqual(m.evaluate(root,self.spec('html_form_labels','index.html'))['review_outcome'],'EVIDENCE_CHECKS_PASS')
            (root/'index.html').write_text('<label>Email <input></label>')
            self.assertEqual(m.evaluate(root,self.spec('html_form_labels','index.html'))['review_outcome'],'EVIDENCE_CHECKS_PASS')
    def test_no_file_writes(self):
        root=ROOT/'cases'/'code'; before={p:str(p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        m.evaluate(root,self.load(root))
        after={p:str(p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
    def test_escape_path_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); (root/'file.txt').write_text('x')
            for bad in ('../file.txt','/etc/passwd','a/../file.txt'):
                self.assertEqual(m.evaluate(root,self.spec('file_exists',bad))['review_outcome'],'BLOCKED')
    def test_symlink_outside_rejected(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as outside:
            root=pathlib.Path(t);p=pathlib.Path(outside)/'secret';p.write_text('secret')
            (root/'link').symlink_to(p)
            self.assertEqual(m.evaluate(root,self.spec('python_syntax','link'))['review_outcome'],'BLOCKED')
    def test_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t);(root/'x').write_text('abc')
            v=m.evaluate(root,self.spec('sha256','x',expected_sha256='0'*64))
            self.assertEqual(v['review_outcome'],'BLOCKED')
    def test_duplicates_rejected(self):
        with self.assertRaises(m.ContractError):
            m.evaluate(ROOT/'cases'/'code',{'schema_version':1,'criteria':[{'id':'X','requirement':'r','probe':{'type':'manual'}},{'id':'X','requirement':'r','probe':{'type':'manual'}}]})
    def test_missing_is_fail(self):
        self.assertEqual(m.evaluate(ROOT/'cases'/'code',self.spec('file_exists','missing.md'))['review_outcome'],'BLOCKED')
    def test_manual_never_passes(self):
        x=m.evaluate(ROOT/'cases'/'code',self.spec('manual'))
        self.assertEqual(x['review_outcome'],'INCOMPLETE')
        self.assertFalse(x['release_approved'])
    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); c=root/'c.json'
            c.write_text(json.dumps(self.spec('file_exists','missing')))
            out=io.StringIO()
            with redirect_stdout(out):rc=m.main(['--root',str(root),'--contract',str(c)])
            self.assertEqual(rc,1)
            self.assertEqual(json.loads(out.getvalue())['review_outcome'],'BLOCKED')
            c.write_text('{}');out=io.StringIO()
            with redirect_stdout(out):rc=m.main(['--root',str(root),'--contract',str(c)])
            self.assertEqual(rc,2)

if __name__=='__main__':unittest.main()
