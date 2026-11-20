#!/usr/bin/env python3
"""v5：验证命令失败的自动计数——"改了代码仍然失败"才算一次修复失败。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import write, rmtree  # noqa: E402
from test_de import Base, steps, read_json, write_json  # noqa: E402
from test_inputs import EXISTS_OK  # noqa: E402

OTHER_OK = [sys.executable, "-c", "import os, sys; sys.exit(0 if os.path.isfile('ok.flag') else 1)"]
UNSTABLE = [sys.executable, "-c", "import sys; open('gen.txt', 'a').write('x'); sys.exit(1)"]


def auto_steps(cmd=EXISTS_OK):
    return steps({1: {"verify_argv": cmd, "depends_on": []},
                  2: {"verify_cmd": None, "verify_argv": EXISTS_OK}})


class AutoBase(Base):
    def setUp(self):
        super().setUp()
        self.ready(st=auto_steps())
        os.remove(os.path.join(self.d, "ok.flag"))
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 0)

    def done(self, sid="1"):
        return self.de("step", sid, "--status", "done")

    def change(self, text):
        write(self.d, "scratch.txt", text)

    def st(self, sid="1"):
        return self.state()["steps"][sid]


class TestCounting(AutoBase):
    def test_first_failure_is_baseline_not_counted(self):
        code, d = self.done()
        self.assertEqual(code, 3, d)
        self.assertFalse(d["counted"])
        self.assertEqual(self.st().get("fails"), 0)
        self.assertFalse(self.st()["last_verify"]["ok"])

    def test_same_fingerprint_repeat_not_counted(self):
        self.done()
        code, d = self.done()
        self.assertFalse(d["counted"])
        self.assertEqual(self.st().get("fails"), 0)

    def test_changed_fingerprint_failure_counts(self):
        self.done()
        self.change("a")
        code, d = self.done()
        self.assertTrue(d["counted"], d)
        self.assertEqual(d["fails"], 1)
        self.assertEqual(self.st()["fails"], 1)
        self.assertEqual(self.st()["fail_mark"]["by"], "auto")

    def test_auto_escalates_at_max_fails_via_step_done(self):
        self.done()
        self.change("a")
        self.done()
        self.change("b")
        code, d = self.done()
        self.assertEqual(code, 3)
        self.assertTrue(d["escalate"], d)
        st = self.st()
        self.assertEqual(st["status"], "needs_replan")
        self.assertEqual(st["escalation"]["source"], "auto")
        self.assertIsNone(d["next"]["cmd"])                       # 先改步骤
        with open(self.p("events.jsonl"), encoding="utf-8") as f:
            self.assertIn('"escalated": true', f.read().splitlines()[-1])
        self.assertEqual(self.de("status")[1]["stage"], "replan")

    def test_auto_escalates_via_verify_all(self):
        self.de("verify", "--all")
        self.change("a")
        self.de("verify", "--all")
        self.change("b")
        code, d = self.de("verify", "--all")
        self.assertEqual(code, 1)
        r1 = next(r for r in d["results"] if r["step"] == 1)
        r2 = next(r for r in d["results"] if r["step"] == 2)
        self.assertTrue(r1["escalated"])
        self.assertFalse(r2["counted"])                           # 步骤 2 还是 todo，只记基线
        self.assertEqual(self.st("2").get("fails"), 0)
        self.assertIsNone(d["next"]["cmd"])

    def test_done_steps_not_counted_by_verify_all(self):
        write(self.d, "ok.flag", "1")
        self.assertEqual(self.done()[0], 0)
        os.remove(os.path.join(self.d, "ok.flag"))
        for t in ("a", "b", "c"):
            self.change(t)
            self.de("verify", "1")
        self.assertEqual(self.st()["status"], "done")
        self.assertEqual(self.st().get("fails"), 0)

    def test_pass_resets_chain_not_fails(self):
        self.done()
        self.change("a")
        self.done()                                               # fails = 1
        write(self.d, "ok.flag", "1")
        self.assertEqual(self.de("verify", "1")[0], 0)            # 通过：只重置基线
        os.remove(os.path.join(self.d, "ok.flag"))
        self.change("b")
        code, d = self.done()
        self.assertFalse(d["counted"])                            # 通过之后的第一次失败是新基线
        self.assertEqual(self.st()["fails"], 1)                   # 但已计的失败不清零

    def test_unstable_run_not_counted_and_chain_kept(self):
        plan = self.plan()
        plan["steps"][0]["verify_argv"] = UNSTABLE
        write_json(self.p("plan.json"), plan)
        self.confirm("gate", "B")
        for _ in range(3):
            code, d = self.done()
            self.assertFalse(d["counted"])
        self.assertEqual(self.st().get("fails"), 0)
        self.assertNotIn("last_verify", self.st())


class TestManualAndAutoDedup(AutoBase):
    def test_manual_fail_after_auto_count_same_fp_not_double_counted(self):
        self.done()
        self.change("a")
        self.done()                                               # 自动计 1
        code, d = self.de("fail", "1", "--note", "同一次失败")
        self.assertFalse(d["counted"], d)
        self.assertEqual(d["fails"], 1)
        code, d = self.de("fail", "1", "--note", "又试了一次")    # 只吸收一次
        self.assertTrue(d["counted"])
        self.assertEqual(d["fails"], 2)

    def test_auto_after_manual_fail_same_fp_not_double_counted(self):
        self.de("verify", "1")                                    # 基线
        self.change("a")
        self.assertTrue(self.de("fail", "1", "--note", "自己跑的测试失败")[1]["counted"])
        code, d = self.de("verify", "1")
        self.assertFalse(d["results"][0]["counted"])
        self.assertEqual(self.st()["fails"], 1)

    def test_manual_fail_repeated_same_fp_still_counts(self):
        self.assertFalse(self.de("fail", "1", "--note", "x")[1]["escalate"])
        self.assertTrue(self.de("fail", "1", "--note", "x")[1]["escalate"])


class TestChainResets(AutoBase):
    def escalate(self):
        self.done()
        self.change("a")
        self.done()
        self.change("b")
        self.assertTrue(self.done()[1]["escalate"])

    def test_waive_then_new_fp_failure_reescalates(self):
        self.escalate()
        self.confirm("replan", "1", "--note", "x", "--waive", "环境问题")
        self.assertEqual(self.st()["fails"], 1)
        self.de("step", "1", "--status", "in_progress")
        self.change("c")
        code, d = self.done()
        self.assertTrue(d["escalate"], d)

    def test_waive_then_same_fp_rerun_not_counted(self):
        self.escalate()
        self.confirm("replan", "1", "--note", "x", "--waive", "环境问题")
        self.de("step", "1", "--status", "in_progress")
        code, d = self.done()
        self.assertFalse(d["counted"], d)
        self.assertEqual(self.st()["fails"], 1)

    def test_replan_clears_chain(self):
        self.escalate()
        plan = self.plan()
        plan["steps"][0]["title"] = "换一种做法"
        write_json(self.p("plan.json"), plan)
        self.assertEqual(self.de("replan", "1", "--note", "已修改")[0], 0)
        self.assertNotIn("last_verify", self.st())
        self.confirm("gate", "B")
        self.de("step", "1", "--status", "in_progress")
        self.change("c")
        code, d = self.done()
        self.assertFalse(d["counted"])
        self.assertEqual(self.st()["fails"], 0)

    def test_reopen_clears_last_verify(self):
        write(self.d, "ok.flag", "1")
        self.assertEqual(self.done()[0], 0)
        self.assertIn("last_verify", self.st())
        self.de("reopen", "1", "--reason", "重做")
        self.assertNotIn("last_verify", self.st())

    def test_changed_verify_command_is_new_baseline(self):
        self.done()
        plan = self.plan()
        plan["steps"][0]["verify_argv"] = OTHER_OK
        write_json(self.p("plan.json"), plan)
        self.confirm("gate", "B")
        self.change("a")
        code, d = self.done()
        self.assertFalse(d["counted"])

    def test_old_workspace_without_last_verify_upgrades(self):
        self.done()
        st = read_json(self.p("state.json"))
        st["steps"]["1"].pop("last_verify")
        write_json(self.p("state.json"), st)
        self.assertEqual(self.de("status")[1]["gates"], {"A": "valid", "B": "valid"})
        self.change("a")
        code, d = self.done()
        self.assertFalse(d["counted"])                            # 升级后的第一次失败是基线


class TestNonGit(Base):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.de("init", "--name", "测试项目")
        self.ready(st=auto_steps())
        self.de("step", "1", "--status", "in_progress")

    def tearDown(self):
        rmtree(self.d, ignore_errors=True)

    def test_non_git_no_auto_counting(self):
        for t in ("a", "b", "c"):
            write(self.d, "scratch.txt", t)
            code, d = self.de("step", "1", "--status", "done")
            self.assertFalse(d["counted"])
        self.assertEqual(self.state()["steps"]["1"].get("fails"), 0)


if __name__ == "__main__":
    unittest.main()
