"""R2/R3 contract checks: read-only preflight, criterion evidence coverage, approval visibility."""
import json
import os
import subprocess
import sys
import unittest
sys.path.insert(0, os.path.dirname(__file__))
from test_de import Base
from helpers import write, DE, call

class TestR2Commands(Base):
    def de(self, *args, cwd=None):
        # Some isolated CI hosts may be heavily loaded; test framework timeout is not
        # the verification command timeout, so allow enough time for subprocess startup.
        return call(DE, cwd or self.d, *args, timeout=180)

    def test_preflight_read_only_without_workspace(self):
        before = open(self.p('plan.json'), 'rb').read()
        code, value = self.de('preflight')
        self.assertEqual(code, 0, value)
        self.assertTrue(value['read_only'])
        self.assertTrue(value['git'])
        self.assertTrue(value['workspace_initialized'])
        self.assertEqual(before, open(self.p('plan.json'), 'rb').read())

    def test_preflight_has_git_branch_and_current_dirty_state(self):
        write(self.d, 'user-change.txt', 'owned by user')
        code, value = self.de('preflight')
        self.assertEqual(code, 0, value)
        self.assertEqual(value['branch'], subprocess.check_output(['git', 'symbolic-ref', '--short', 'HEAD'], cwd=self.d, text=True).strip())
        self.assertGreater(value['dirty_file_count'], 0)
        self.assertIn('user-change.txt', value['dirty_paths_preview'])
        self.assertTrue(os.path.isfile(os.path.join(self.d, 'user-change.txt')))

    def test_preflight_reports_commands_without_running_them(self):
        self.set_card()
        self.set_plan()
        plan=self.plan()
        plan['steps'][1]['verify_cmd']='rm -rf danger-sentinel'
        write(self.d,'.decision/plan.json',json.dumps(plan))
        write(self.d,'danger-sentinel', 'must be intact')
        code,value=self.de('preflight')
        self.assertEqual(code,0,value)
        self.assertTrue(value['verification_commands'][0]['review_required'])
        self.assertIn('可能删除或破坏文件',value['verification_commands'][0]['hazards'])
        self.assertTrue(os.path.isfile(os.path.join(self.d,'danger-sentinel')))

    def test_gate_b_preview_surfaces_command_risks(self):
        self.set_card()
        self.set_plan()
        plan=self.plan()
        plan['steps'][1]['verify_cmd']='rm -rf danger-sentinel'
        write(self.d,'.decision/plan.json',json.dumps(plan))
        self.confirm('gate','A')
        code,value=self.de('gate','B')
        self.assertEqual(code,3,value)
        items=value['preview']['steps']
        self.assertEqual(len(items),2)
        self.assertIn('可能删除或破坏文件', items[1]['verify_command_risk_hints'])

    def test_coverage_marks_notes_unverified_not_pass(self):
        self.finish()
        code,value=self.de('coverage')
        self.assertEqual(code,0,value)
        self.assertTrue(value['read_only'])
        by_id={x['criterion']:x for x in value['criteria']}
        self.assertEqual(by_id[1]['status'],'NEEDS_VERIFICATION')
        self.assertEqual(by_id[2]['status'],'READY_FOR_INDEPENDENT_REVIEW')
        self.assertFalse(value['all_ready_for_review'])

    def test_coverage_artifact_requires_independent_review(self):
        self.ready()
        write(self.d,'proof.txt','some artifact')
        self.de('step','1','--status','in_progress')
        self.assertEqual(self.de('step','1','--status','done','--artifact','proof.txt')[0],0)
        self.de('step','2','--status','in_progress')
        self.assertEqual(self.de('step','2','--status','done')[0],0)
        code,value=self.de('coverage')
        self.assertEqual(code,0,value)
        self.assertTrue(value['all_ready_for_review'])
        self.assertEqual(value['criteria'][0]['steps'][0]['evidence_quality'],'ARTIFACT_INTACT')
        self.assertIn('不证明', ' '.join(value['limits']))

    def test_coverage_stale_after_artifact_changes(self):
        self.ready()
        write(self.d,'proof.txt','ONE')
        self.de('step','1','--status','in_progress')
        self.de('step','1','--status','done','--artifact','proof.txt')
        self.de('step','2','--status','in_progress')
        self.de('step','2','--status','done')
        write(self.d,'proof.txt','TWO')
        code,value=self.de('coverage')
        self.assertEqual(code,0,value)
        self.assertEqual(value['criteria'][0]['status'],'STALE')
        self.assertFalse(value['all_ready_for_review'])

    def test_coverage_before_any_gates_does_not_approve(self):
        self.set_card()
        self.set_plan()
        code,value=self.de('coverage')
        self.assertEqual(code,0,value)
        self.assertEqual([x['status'] for x in value['criteria']],['NEEDS_VERIFICATION']*2)

if __name__=='__main__': unittest.main()
