"""输入格式与跨平台验证命令：方括号不是占位符、verify_argv 不经 shell 执行。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_de import CARD, Base, steps  # noqa: E402
from helpers import write  # noqa: E402

EXISTS_OK = [sys.executable, "-c", "import os, sys; sys.exit(0 if os.path.exists('ok.flag') else 1)"]


class TestBracketsAreContent(Base):
    def test_brackets_in_criteria_and_titles_are_kept(self):
        self.set_card(CARD.replace("2. 测试命令退出码为 0", "2. 接口对非法输入返回 [400]，对 [] 返回空列表"))
        code, d = self.de("check", "card")
        self.assertEqual(code, 0, d)
        self.set_plan(st=steps({1: {"title": "修复 [P1] 登录超时"}}))
        code, d = self.de("check", "plan")
        self.assertEqual(code, 0, d)
        self.assertFalse(any("没有任何步骤覆盖" in w for w in d["warnings"]), d)

    def test_template_placeholders_still_rejected(self):
        self.set_card(CARD.replace("三个月内确认是否有人付费。", "[一句话，描述结果而不是动作]"))
        code, d = self.de("check", "card")
        self.assertEqual(code, 1)
        self.assertTrue(any("目标" in e for e in d["errors"]), d)


class TestVerifyArgv(Base):
    def argv_steps(self, argv):
        return steps({2: {"verify_cmd": "", "verify_argv": argv}})

    def test_argv_runs_without_shell(self):
        self.ready(st=self.argv_steps(EXISTS_OK))
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "访谈记录")
        self.de("step", "2", "--status", "in_progress")
        os.remove(os.path.join(self.d, "ok.flag"))
        self.assertEqual(self.de("step", "2", "--status", "done")[0], 3)
        write(self.d, "ok.flag", "1")
        code, d = self.de("step", "2", "--status", "done")
        self.assertEqual((code, d["evidence_kind"]), (0, "command"), d)

    def test_missing_executable_is_a_failure_not_a_crash(self):
        self.ready(st=self.argv_steps(["definitely-not-a-real-binary-xyz"]))
        code, d = self.de("verify", "2")
        self.assertEqual(code, 1, d)
        self.assertEqual(d["results"][0]["exit_code"], 127)

    def test_gate_b_preview_shows_argv_command(self):
        self.set_card()
        self.set_plan(st=self.argv_steps(EXISTS_OK))
        self.confirm("gate", "A")
        code, d = self.de("gate", "B")
        self.assertEqual(code, 3, d)
        item = d["preview"]["steps"][1]
        self.assertIn("ok.flag", item["verify_command"])
        self.assertFalse(item["runs_via_shell"])

    def test_argv_type_and_conflict_checked(self):
        self.set_card()
        self.set_plan(st=steps({2: {"verify_argv": "pytest"}}))
        self.assertEqual(self.de("check", "plan")[0], 2)
        self.set_plan(st=steps({2: {"verify_argv": ["pytest"]}}))   # 同时保留了 verify_cmd
        code, d = self.de("check", "plan")
        self.assertEqual(code, 1, d)
        self.assertTrue(any("只能保留一种" in e for e in d["errors"]), d)

    def test_old_plans_keep_gate_b_after_upgrade(self):
        self.ready()
        p = self.plan()
        self.assertTrue(all("verify_argv" not in s for s in p["steps"]))
        self.assertEqual(self.de("status")[1]["gates"]["B"], "valid")
        json.dumps(p)


if __name__ == "__main__":
    unittest.main()
