#!/usr/bin/env python3
"""v5：每个 JSON 输出都带 next = {cmd, why[, needs_user]}，并且照着 next.cmd 能走完整个生命周期。"""
import os
import shlex
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import DE, ENV, call, commit_all, write  # noqa: E402
from test_de import Base, CARD, RETRO, steps, read_json, write_json  # noqa: E402

FILL = {"<证据>": "访谈记录 5 份", "<说明>": "已修改步骤", "<原因>": "重新验证", "<证据文件>": "ok.flag"}
REPORT = "# 收尾报告\n\n文档与代码一致，静态审计 error 0，无需修改。\n"


def argv_of(cmd):
    """把 next.cmd 里的 de.py 简写换成测试用的脚本参数，并替换占位符。"""
    parts = shlex.split(cmd)
    assert parts[0] == "de.py", cmd
    return [FILL.get(p, p) for p in parts[1:]]


class NextBase(Base):
    def assert_next(self, d):
        self.assertIn("next", d, d)
        n = d["next"]
        self.assertIsInstance(n, dict, d)
        self.assertTrue(isinstance(n.get("why"), str) and n["why"], d)
        self.assertTrue(n.get("cmd") is None or (isinstance(n["cmd"], str) and n["cmd"].startswith("de.py ")), d)
        return n

    def run_next(self, d, cwd=None):
        n = self.assert_next(d)
        self.assertIsNotNone(n["cmd"], d)
        return self.de(*argv_of(n["cmd"]), cwd=cwd)


class TestNextShape(NextBase):
    def test_every_json_output_has_next_object(self):
        outputs = [self.de("status"), self.de("check", "card"), self.de("check", "plan"), self.de("list"),
                   self.de("preflight"), self.de("gate", "B"), self.de("step", "1", "--status", "in_progress"),
                   self.de("verify", "2")]
        self.set_card()
        self.set_plan()
        outputs += [self.de("gate", "AB"), self.de("coverage"), self.de("archive"), self.de("purge"),
                    self.de("reopen", "1", "--reason", "x"), self.de("fail", "1", "--note", "x"),
                    self.de("replan", "1", "--note", "x"), self.de("review", "--verdict", "pass")]
        for code, d in outputs:
            self.assert_next(d)

    def test_refusal_outside_project_has_next(self):
        code, d = call(DE, self.d, "status", "--dir", os.path.dirname(self.d))
        self.assertEqual(code, 2)
        self.assertIsNone(self.assert_next(d)["cmd"])

    def test_confirm_preview_next_has_token_and_needs_user(self):
        self.set_card()
        self.set_plan()
        code, d = self.de("gate", "AB")
        self.assertEqual(code, 3)
        n = self.assert_next(d)
        self.assertTrue(n.get("needs_user"))
        self.assertIn("--confirm " + d["token"], n["cmd"])

    def test_gate_refusal_next_points_to_stale_gate(self):
        self.ready()
        self.set_card(CARD.replace("三个月内", "六个月内"))
        code, d = self.de("step", "1", "--status", "in_progress")
        self.assertEqual(code, 3)
        self.assertEqual(self.assert_next(d)["cmd"], "de.py gate AB")

    def test_high_risk_never_suggests_gate_ab(self):
        self.set_card()
        self.set_plan(risk="high")
        st = self.de("status")[1]
        self.assertEqual(st["stage"], "direction")
        self.assertEqual(st["next"]["cmd"], "de.py gate A")


class TestNextPerStage(NextBase):
    def test_direction_fill_card_then_gate_ab(self):
        st = self.de("status")[1]
        self.assertEqual(st["next"]["cmd"], "de.py check card")
        self.set_card()
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py gate A")     # 计划还是模板
        self.set_plan()
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py gate AB")

    def test_execute_starts_first_step_then_finishes_it(self):
        self.ready()
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py step 1 --status in_progress")
        self.de("step", "1", "--status", "in_progress")
        n = self.de("status")[1]["next"]
        self.assertTrue(n["cmd"].startswith("de.py step 1 --status done --evidence "))

    def test_current_step_respects_dependencies_and_blocked(self):
        self.ready()
        self.de("step", "1", "--status", "blocked")
        st = self.de("status")[1]
        self.assertEqual(st["current_step"]["id"], 1)              # 不会跳到依赖 1 的步骤 2
        code, d = self.run_next(st)
        self.assertEqual(code, 0, d)

    def test_current_step_uses_first_step(self):
        self.set_card()
        self.set_plan(st=steps({2: {"depends_on": []}}))
        plan = self.plan()
        plan["first_step"] = 2
        write_json(self.p("plan.json"), plan)
        self.confirm("gate", "AB")
        self.assertEqual(self.de("status")[1]["current_step"]["id"], 2)

    def test_current_step_prefers_implemented(self):
        self.ready(st=steps({2: {"depends_on": []}}))
        self.de("step", "2", "--status", "in_progress")
        self.de("step", "2", "--status", "implemented")
        self.assertEqual(self.de("status")[1]["current_step"]["id"], 2)
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py step 2 --status done")

    def test_execute_ignores_stale_evidence(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "x")
        self.de("step", "2", "--status", "in_progress")
        write(self.d, "src.txt", "changed")
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py step 2 --status done")

    def test_review_stage_stale_command_suggests_verify_all(self):
        self.finish()
        commit_all(self.d)
        st = self.de("status")[1]
        self.assertEqual(st["stage"], "review")
        self.assertEqual(st["next"]["cmd"], "de.py verify --all")

    def test_review_stage_stale_artifact_suggests_reopen(self):
        write(self.d, "report.txt", "evidence")
        self.ready(st=steps({2: {"verify_cmd": None}}))
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "x")
        self.de("step", "2", "--status", "in_progress")
        self.assertEqual(self.de("step", "2", "--status", "done", "--artifact", "report.txt")[0], 0)
        write(self.d, "report.txt", "changed evidence")
        st = self.de("status")[1]
        self.assertEqual(st["stage"], "review")
        self.assertTrue(st["next"]["cmd"].startswith("de.py reopen 2 --reason "))

    def test_review_pass_then_retro_then_closeout(self):
        self.finish()
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py review --verdict pass")
        self.confirm("review", "--verdict", "pass")
        n = self.de("status")[1]["next"]
        self.assertIsNone(n["cmd"])
        self.assertIn("retro.md", n["why"])
        write(self.d, ".decision/retro.md", RETRO)
        self.assertTrue(self.de("status")[1]["next"]["cmd"].startswith("de.py closeout --report "))

    def test_review_fix_verdict_next_is_check_plan(self):
        self.finish()
        self.confirm("review", "--verdict", "fix", "--blocker", "缺少回滚")
        self.assertEqual(self.de("status")[1]["next"]["cmd"], "de.py check plan")

    def test_replan_edit_then_next_suggests_replan_before_gate_b(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.de("fail", "1", "--note", "x")
        d = self.de("fail", "1", "--note", "x")[1]
        self.assertTrue(d["escalate"])
        self.assertIsNone(d["next"]["cmd"])                          # 先改步骤，脚本不能替你改
        plan = self.plan()
        plan["steps"][0]["title"] = "访谈（改为当面）"
        write_json(self.p("plan.json"), plan)
        st = self.de("status")[1]
        self.assertEqual(st["stage"], "plan")
        self.assertTrue(st["next"]["cmd"].startswith("de.py replan 1 --note "))
        code, d = self.run_next(st)
        self.assertEqual(code, 0, d)
        self.assertEqual(d["next"]["cmd"], "de.py gate B")

    def test_deadline_hit_next_defers_to_user(self):
        self.set_card(CARD.replace("2099-11-30", "2000-01-01"))
        self.set_plan()
        self.confirm("gate", "AB")
        n = self.de("status")[1]["next"]
        self.assertIsNone(n["cmd"])
        self.assertIn("2000-01-01", n["why"])


class TestNextDir(NextBase):
    def test_next_includes_dir_for_non_default_workspace(self):
        self.de("init", "--dir", ".decision-b")
        d = self.de("status", "--dir", ".decision-b")[1]
        self.assertIn("--dir .decision-b", d["next"]["cmd"])

    def test_next_dir_from_env_var(self):
        self.de("init", "--dir", ".decision-b")
        old = ENV.get("DE_WORKSPACE")
        ENV["DE_WORKSPACE"] = ".decision-b"
        try:
            d = self.de("status")[1]
        finally:
            if old is None:
                ENV.pop("DE_WORKSPACE", None)
            else:
                ENV["DE_WORKSPACE"] = old
        self.assertIn("--dir .decision-b", d["next"]["cmd"])

    def test_next_dir_relative_to_cwd_from_subdirectory(self):
        self.de("init", "--dir", ".decision-b")
        sub = os.path.join(self.d, "src", "deep")
        os.makedirs(sub)
        d = self.de("status", "--dir", "../../.decision-b", cwd=sub)[1]
        code, d2 = self.run_next(d, cwd=sub)
        self.assertNotEqual(code, 2, d2)                              # 目录解析正确，不是用法错误


class TestNextLifecycle(NextBase):
    def test_next_chain_drives_full_lifecycle(self):
        """从 init 到 purge：每一步要么照 next.cmd 运行，要么做 why 描述的人工工作。"""
        self.set_card()
        self.set_plan()
        d = self.de("status")[1]
        seen = []
        for _ in range(40):
            n = self.assert_next(d)
            seen.append(n["cmd"])
            if n["cmd"] is None:
                if "retro.md" in n["why"]:
                    write(self.d, ".decision/retro.md", RETRO)
                elif "提交这次删除" in n["why"]:
                    break
                else:
                    self.fail("unexpected manual step: %s" % n)
                d = self.de("status")[1]
                continue
            argv = argv_of(n["cmd"])
            if argv[0] in ("closeout", "sync"):
                write(self.d, ".decision/closeout-report.md", REPORT)
            if argv[0] == "purge":
                commit_all(self.d)
            code, d = self.de(*argv)
            self.assertNotEqual(code, 2, (n, d))
            self.assertFalse(d.get("gates") and d.get("refused") and "闸门" in d.get("reason", ""), (n, d))
            if code == 3 and d.get("needs_confirmation"):
                self.assertTrue(d["next"].get("needs_user"), d)
                code, d = self.de(*argv_of(d["next"]["cmd"]))
                self.assertEqual(code, 0, d)
        else:
            self.fail("lifecycle did not finish: %s" % seen)
        self.assertFalse(os.path.exists(self.p()), seen)


if __name__ == "__main__":
    unittest.main()
