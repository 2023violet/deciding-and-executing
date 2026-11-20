#!/usr/bin/env python3
"""v6：标准档最小决策卡（B1）与轻量验证入口 de.py prove（C3）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import DE, call, rmtree, write  # noqa: E402
from test_de import Base, CARD, steps  # noqa: E402

MINIMAL = """# 决策卡：最小卡

- 结论：做
- 置信度及依据：中，依据是已有的测试覆盖

## 目标
把订单服务迁到 PostgreSQL。

## 成功标准
1. 测试命令退出码为 0
2. 迁移后订单数与迁移前一致

## 止损条件
- 触发状态：两周内数据校验仍不一致
- 期限：2099-11-30
- 动作：回退到 SQLite
"""

PY_OK = [sys.executable, "-c", "print('ok')"]
PY_FAIL = [sys.executable, "-c", "import sys; sys.exit(3)"]
PY_WRITE = [sys.executable, "-c", "open('gen.txt', 'a').write('x')"]


class TestMinimalCard(Base):
    def test_standard_card_needs_only_goal_criteria_stoploss(self):
        self.set_card(MINIMAL)
        code, d = self.de("check", "card")
        self.assertEqual(code, 0, d)
        self.set_plan(st=steps({1: {"tests_assumption": None}}))
        self.confirm("gate", "AB")
        self.assertEqual(self.de("status")[1]["gates"], {"A": "valid", "B": "valid"})

    def test_template_placeholders_in_optional_sections_are_fine(self):
        # init 生成的模板里非目标和关键假设只有占位符：标准档不算错
        path = self.p("decision-card.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text = text.replace("- 结论：[做 / 改后做 / 放弃 三选一开头，可在括号里补充说明]", "- 结论：做")
        text = text.replace("[一句话，描述结果而不是动作]", "迁移订单服务")
        text = text.replace("1. [可观察、可验证，最好带数字或明确的验收人；计划用编号建立覆盖关系]", "1. 测试退出码为 0")
        text = text.replace("- 触发状态：[可观察的状态，例如：还没有 1 家店预付或签意向书]", "- 触发状态：校验不一致")
        text = text.replace("- 期限：[YYYY-MM-DD]", "- 期限：2099-11-30")
        text = text.replace("- 动作：[停止 / 转向 X]", "- 动作：回退")
        write(self.d, ".decision/decision-card.md", text)
        code, d = self.de("check", "card")
        self.assertEqual(code, 0, d)

    def test_standard_assumptions_written_must_be_numbered(self):
        self.set_card(MINIMAL + "\n## 关键假设\n用户愿意付费\n")
        code, d = self.de("check", "card")
        self.assertEqual(code, 1)
        self.assertTrue(any("A1" in e for e in d["errors"]), d)

    def test_high_risk_still_requires_all_sections(self):
        self.set_card(MINIMAL)
        self.set_plan(risk="high")
        code, d = self.de("check", "card")
        self.assertEqual(code, 1)
        self.assertTrue(any("非目标" in e for e in d["errors"]), d)
        self.assertTrue(any("关键假设" in e for e in d["errors"]), d)

    def test_full_card_gate_hash_unchanged_for_existing_workspaces(self):
        # 写全五节的卡（旧工作区的样子）：确认后仍然有效
        self.ready()
        self.assertEqual(self.de("status")[1]["gates"], {"A": "valid", "B": "valid"})

    def test_english_optional_heading_parses(self):
        self.de("init", "--dir", ".decision-en", "--lang", "en")
        with open(os.path.join(self.d, ".decision-en", "decision-card.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Non-goals (optional in the standard tier)", text)


class TestProve(Base):
    def prove(self, *cmd, cwd=None):
        return call(DE, cwd or self.d, "prove", "--", *cmd)

    def test_passing_command_is_verified(self):
        code, d = self.prove(*PY_OK)
        self.assertEqual(code, 0, d)
        self.assertEqual(d["verdict"], "verified")
        self.assertTrue(d["fingerprint"])
        self.assertIn("next", d)

    def test_failing_command(self):
        code, d = self.prove(*PY_FAIL)
        self.assertEqual(code, 1)
        self.assertEqual((d["verdict"], d["exit_code"]), ("failed", 3))

    def test_code_changed_during_run_is_not_verified(self):
        code, d = self.prove(*PY_WRITE)
        self.assertEqual(code, 1)
        self.assertEqual(d["verdict"], "failed")

    def test_needs_no_workspace_and_writes_nothing(self):
        rmtree(self.p())
        before = sorted(os.listdir(self.d))
        code, d = self.prove(*PY_OK)
        self.assertEqual(code, 0, d)
        self.assertEqual(before, sorted(os.listdir(self.d)))

    def test_workspace_hint_when_present(self):
        code, d = self.prove(*PY_OK)
        self.assertEqual(d["next"]["cmd"], "de.py status")

    def test_shell_mode(self):
        code, d = call(DE, self.d, "prove", "--shell", "--", "echo hello")
        self.assertEqual(code, 0, d)

    def test_missing_command_is_usage_error(self):
        code, d = call(DE, self.d, "prove")
        self.assertEqual(code, 2)

    def test_non_git_is_unverifiable(self):
        d0 = os.path.realpath(tempfile.mkdtemp())
        try:
            code, d = call(DE, d0, "prove", "--", *PY_OK)
            self.assertEqual(code, 1)
            self.assertEqual(d["verdict"], "unverifiable")
        finally:
            rmtree(d0, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
