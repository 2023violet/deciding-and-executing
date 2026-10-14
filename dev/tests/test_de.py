#!/usr/bin/env python3
"""de.py 回归与对抗测试。用法: python3 -m unittest discover -s dev/tests"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import DE, AUDIT, call, commit_all, init_repo, write  # noqa: E402

CARD = """# 决策卡：测试项目

- 日期：2026-10-12
- 结论：改后做（先业余验证）
- 置信度及依据：中，依据是两次访谈

## 目标
三个月内确认是否有人付费。

## 成功标准
1. 到 2027-01-10 至少 3 家付费
2. 测试命令退出码为 0

## 非目标
- 不做外卖

## 关键假设
| # | 假设 | 后果 | 状态 |
|---|---|---|---|
| A1 | 店主愿意付费 | 方向不成立 | 未验证 |

## 止损条件
- 触发状态：还没有 1 家预付
- 期限：2099-11-30
- 动作：停止开发

## 升级阈值
- 修复失败次数上限：2
"""

RETRO = "# 复盘\n\n## 原本预期\n3 家付费\n\n## 实际发生\n2 家付费\n\n## 差异的原因\n价格偏高\n"


def steps(over=None):
    over = over or {}
    base = [
        {"id": 1, "title": "访谈", "done_when": "5 份记录", "verify": "记录文件", "covers": [1],
         "tests_assumption": "A1", "estimate_h": 4, "status": "todo", "fails": 0, "evidence": []},
        {"id": 2, "title": "测试", "done_when": "退出码 0", "verify": "运行检查", "verify_cmd": "test -f ok.flag",
         "covers": [2], "depends_on": [1], "estimate_h": 4, "status": "todo", "fails": 0, "evidence": []},
    ]
    for s in base:
        s.update(over.get(s["id"], {}))
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        init_repo(self.d)
        write(self.d, "ok.flag", "1")
        self.de("init", "--name", "测试项目")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def de(self, *args, cwd=None):
        return call(DE, cwd or self.d, *args)

    def p(self, *parts):
        return os.path.join(self.d, ".decision", *parts)

    def set_card(self, text=CARD):
        write(self.d, ".decision/decision-card.md", text)

    def set_plan(self, risk="standard", st=None):
        path = self.p("plan.json")
        plan = json.load(open(path, encoding="utf-8"))
        plan.update(risk=risk, steps=st or steps(), first_step=1,
                    if_then=[{"if": "a", "then": "b"}, {"if": "c", "then": "d"}])
        json.dump(plan, open(path, "w", encoding="utf-8"), ensure_ascii=False)

    def plan(self):
        return json.load(open(self.p("plan.json"), encoding="utf-8"))

    def confirm(self, *args):
        code, d = self.de(*args)
        self.assertEqual(code, 3, d)
        self.assertTrue(d.get("needs_confirmation"), d)
        code, d = self.de(*(list(args) + ["--confirm", d["token"]]))
        self.assertEqual(code, 0, d)
        return d

    def ready(self, risk="standard", st=None):
        self.set_card()
        self.set_plan(risk, st)
        self.confirm("gate", "A")
        self.confirm("gate", "B")

    def finish(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.assertEqual(self.de("step", "1", "--status", "done", "--evidence", "访谈记录")[0], 0)
        self.de("step", "2", "--status", "in_progress")
        self.assertEqual(self.de("step", "2", "--status", "done")[0], 0)


class TestWorkspaceSafety(Base):
    """WP-01：删除与归档安全（评审 P0-01、F-07、F-08）。"""

    def test_dir_cannot_be_project_root(self):
        code, d = self.de("status", "--dir", ".")
        self.assertEqual(code, 2)
        code, d = self.de("purge", "--dir", self.d)
        self.assertEqual(code, 2)
        self.assertTrue(os.path.isdir(os.path.join(self.d, ".git")))

    def test_dir_outside_project_refused(self):
        other = tempfile.mkdtemp()
        try:
            code, _ = self.de("init", "--dir", other)
            self.assertEqual(code, 2)
        finally:
            shutil.rmtree(other)

    def test_symlink_workspace_refused(self):
        outside = tempfile.mkdtemp()
        try:
            os.symlink(outside, os.path.join(self.d, "ws"))
            code, d = self.de("init", "--dir", "ws")
            self.assertEqual(code, 2)
            self.assertIn("符号链接", d["reason"])
        finally:
            shutil.rmtree(outside)

    def test_init_refuses_nonempty_foreign_dir(self):
        write(self.d, "notes/keep.txt", "x")
        code, _ = self.de("init", "--dir", "notes")
        self.assertEqual(code, 2)
        self.assertTrue(os.path.exists(os.path.join(self.d, "notes", "keep.txt")))

    def test_subdirectory_uses_same_workspace(self):
        os.makedirs(os.path.join(self.d, "src", "deep"))
        code, d = self.de("status", cwd=os.path.join(self.d, "src", "deep"))
        self.assertEqual(code, 0, d)
        self.assertFalse(os.path.exists(os.path.join(self.d, "src", "deep", ".decision")))

    def test_forged_archived_marker_refused(self):
        write(self.d, "important.txt", "keep")
        write(self.d, ".decision/ARCHIVED", json.dumps({"record": "../../etc/passwd", "synced": True}))
        code, d = self.de("purge")
        self.assertEqual(code, 3)
        write(self.d, ".decision/ARCHIVED", json.dumps({"record": "important.txt", "synced": True}))
        code, d = self.de("purge")
        self.assertEqual(code, 3)
        self.assertTrue(os.path.exists(os.path.join(self.d, "important.txt")))
        self.assertTrue(os.path.isdir(self.p()))

    def test_docs_dir_outside_project_refused(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        code, d = self.de("archive", "--docs-dir", "/tmp", "--apply")
        self.assertEqual(code, 3)
        self.assertTrue(any("docs-dir" in x for x in d["problems"]))

    def test_archive_never_deletes(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        code, d = self.de("archive", "--apply")
        self.assertEqual(code, 0, d)
        self.assertTrue(os.path.isdir(self.p()))

    def full_close(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        self.assertEqual(self.de("archive", "--apply")[0], 0)
        code, audit = call(AUDIT, self.d)
        json.dump(audit, open(self.p("closeout-audit.json"), "w", encoding="utf-8"), ensure_ascii=False)
        write(self.d, ".decision/closeout-report.md", "# 收尾报告\n\n文档与代码一致，静态审计 error 0，无需修改。\n")
        return audit

    def test_purge_requires_sync_commit_and_token(self):
        self.full_close()
        self.assertEqual(self.de("purge")[0], 3)                        # 未 sync
        code, d = self.de("sync", "--audit-json", self.p("closeout-audit.json"),
                          "--report", self.p("closeout-report.md"))
        self.assertEqual(code, 0, d)
        code, d = self.de("purge")
        self.assertEqual(code, 3)
        self.assertIn("未提交", d["reason"])                              # 未提交
        commit_all(self.d)
        code, d = self.de("purge", "--confirm", "0000000000")
        self.assertEqual(code, 3)                                         # 错误 token
        self.assertTrue(os.path.isdir(self.p()))
        self.confirm("purge")
        self.assertFalse(os.path.exists(self.p()))
        self.assertTrue(os.path.isdir(os.path.join(self.d, ".git")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "ok.flag")))

    def test_purge_refuses_unknown_files(self):
        self.full_close()
        self.de("sync", "--audit-json", self.p("closeout-audit.json"), "--report", self.p("closeout-report.md"))
        write(self.d, ".decision/my-notes.txt", "user data")
        commit_all(self.d)
        code, d = self.de("purge")
        self.assertEqual(code, 3)
        self.assertIn("my-notes.txt", " ".join(d.get("unknown", [])))

    def test_sync_uses_live_audit_even_if_supplied_json_is_stale(self):
        self.full_close()
        write(self.d, "README.md", "# changed after saved audit\n")
        code, d = self.de("sync", "--audit-json", self.p("closeout-audit.json"),
                          "--report", self.p("closeout-report.md"))
        self.assertEqual(code, 0, d)
        saved = json.load(open(self.p("closeout-audit.json"), encoding="utf-8"))
        self.assertTrue(saved["complete"])
        self.assertEqual(saved["summary"]["error"], 0)
        self.assertIn("README.md", saved["inventory"]["changed_files"])

    def test_sync_rejects_audit_output_outside_workspace(self):
        self.full_close()
        code, d = self.de("sync", "--audit-json", os.path.join(self.d, "report.json"),
                          "--report", self.p("closeout-report.md"))
        self.assertEqual(code, 2, d)
        self.assertFalse(os.path.exists(os.path.join(self.d, "report.json")))


class TestStateMachine(Base):
    """WP-02：状态机与升级（评审 P1-03、P1-05）。"""

    def test_execution_requires_gate_b(self):
        self.set_card()
        self.set_plan()
        code, d = self.de("step", "1", "--status", "in_progress")
        self.assertEqual(code, 3)
        self.assertEqual(d["gates"]["B"], "missing")

    def test_plan_change_invalidates_gate_b(self):
        self.ready()
        plan = self.plan()
        plan["steps"][0]["verify"] = "换了验证方法"
        json.dump(plan, open(self.p("plan.json"), "w", encoding="utf-8"), ensure_ascii=False)
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 3)
        self.assertEqual(self.de("status")[1]["stage"], "plan")

    def test_card_core_change_invalidates_both_gates(self):
        self.ready()
        self.set_card(CARD.replace("三个月内", "六个月内"))
        st = self.de("status")[1]
        self.assertEqual(st["gates"], {"A": "stale", "B": "stale"})
        self.assertEqual(st["stage"], "direction")

    def test_card_assumption_status_update_keeps_gates(self):
        self.ready()
        self.set_card(CARD.replace("| 未验证 |", "| 已证实 |"))
        self.assertEqual(self.de("status")[1]["gates"], {"A": "valid", "B": "valid"})

    def test_escalation_blocks_until_replan(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.assertFalse(self.de("fail", "1", "--note", "x")[1]["escalate"])
        code, d = self.de("fail", "1", "--note", "x")
        self.assertTrue(d["escalate"])
        self.assertEqual(d["status"], "needs_replan")
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 3)
        self.assertEqual(self.de("step", "1", "--status", "done", "--evidence", "x")[0], 3)
        self.assertEqual(self.de("replan", "1", "--note", "没改")[0], 3)       # 未修改步骤
        plan = self.plan()
        plan["steps"][0]["title"] = "访谈（改为当面）"
        json.dump(plan, open(self.p("plan.json"), "w", encoding="utf-8"), ensure_ascii=False)
        code, d = self.de("replan", "1", "--note", "改为当面访谈")
        self.assertEqual(code, 0, d)
        self.assertEqual(d["gates"]["B"], "stale")
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 3)  # 需重新确认 gate B
        self.confirm("gate", "B")
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 0)

    def test_waiver_requires_confirmation_and_reescalates(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.de("fail", "1", "--note", "x")
        self.de("fail", "1", "--note", "x")
        self.confirm("replan", "1", "--note", "网络抖动", "--waive", "外部服务临时故障，非方案问题")
        self.de("step", "1", "--status", "in_progress")
        self.assertTrue(self.de("fail", "1", "--note", "又失败")[1]["escalate"])

    def test_illegal_transitions(self):
        self.ready()
        self.assertEqual(self.de("step", "1", "--status", "done", "--evidence", "x")[0], 2)  # todo→done
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "x")
        self.assertEqual(self.de("step", "1", "--status", "todo")[0], 3)                    # done→todo

    def test_reopen_archives_evidence_and_voids_review(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        code, d = self.de("reopen", "1", "--reason", "发现访谈样本有偏差")
        self.assertEqual(code, 0)
        s = self.plan()["steps"][0]
        self.assertEqual(s["evidence"], [])
        self.assertEqual(s["evidence_history"][0]["evidence"][0]["text"], "访谈记录")
        self.assertNotIn("review", self.plan())

    def test_dependencies_enforced(self):
        self.ready()
        self.assertEqual(self.de("step", "2", "--status", "in_progress")[0], 3)

    def test_irreversible_step_needs_confirmation(self):
        self.ready(st=steps({1: {"irreversible": True}}))
        code, d = self.de("step", "1", "--status", "in_progress")
        self.assertEqual(code, 3)
        self.assertTrue(d["needs_confirmation"])
        self.confirm("step", "1", "--status", "in_progress")

    def test_hours_overrun_escalates(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress", "--hours", "9")
        self.assertTrue(any("超过预计" in e for e in self.de("status")[1]["escalations"]))

    def test_event_log_consistency_detected(self):
        self.ready()
        with open(self.p("events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"seq": 999, "type": "step"}) + "\n")
        self.assertTrue(any("落后于事件日志" in w for w in self.de("status")[1]["warnings"]))


class TestEvidenceAndReview(Base):
    """WP-03/04：闸门真实性、证据与审查（评审 P1-01、P1-02、P1-04）。"""

    def test_verify_cmd_overrides_subjective_text(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "x")
        self.de("step", "2", "--status", "in_progress")
        os.remove(os.path.join(self.d, "ok.flag"))
        code, d = self.de("step", "2", "--status", "done", "--evidence", "应该已经通过了")
        self.assertEqual(code, 3)
        self.assertEqual(self.plan()["steps"][1]["status"], "in_progress")
        write(self.d, "ok.flag", "1")
        code, d = self.de("step", "2", "--status", "done")
        self.assertEqual((code, d["evidence_kind"]), (0, "command"))

    def test_high_risk_rejects_note_evidence(self):
        self.ready(risk="high")
        self.de("step", "1", "--status", "in_progress")
        self.assertEqual(self.de("step", "1", "--status", "done", "--evidence", "应该好了")[0], 3)
        write(self.d, "notes/interviews.md", "5 份记录")
        code, d = self.de("step", "1", "--status", "done", "--artifact", "notes/interviews.md")
        self.assertEqual((code, d["evidence_kind"]), (0, "artifact"))

    def test_artifact_must_be_inside_project(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.assertEqual(self.de("step", "1", "--status", "done", "--artifact", "/etc/hostname")[0], 2)

    def test_old_revision_evidence_is_stale(self):
        self.finish()
        commit_all(self.d)
        st = self.de("status")[1]
        self.assertEqual(st["stale_evidence_steps"], ["2"])
        code, d = self.de("review", "--verdict", "pass")
        self.assertEqual(code, 3)
        self.assertEqual(self.de("verify", "--all")[0], 0)
        self.confirm("review", "--verdict", "pass")

    def test_note_only_steps_reported(self):
        self.finish()
        self.assertEqual(self.de("status")[1]["note_only_done_steps"], ["1"])

    def test_failed_review_blocks_complete_archive(self):
        self.finish()
        self.confirm("review", "--verdict", "fail", "--blocker", "付费流程有严重缺陷")
        write(self.d, ".decision/retro.md", RETRO)
        code, d = self.de("archive", "--apply")
        self.assertEqual(code, 3)
        self.assertTrue(any("pass" in x for x in d["problems"]))
        self.assertEqual(self.de("archive", "--outcome", "止损")[0], 0)

    def test_pass_with_blockers_refused(self):
        self.finish()
        code, d = self.de("review", "--verdict", "pass", "--blocker", "x")
        self.assertEqual(code, 3)

    def test_retro_template_rejected(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        code, d = self.de("archive")
        self.assertEqual(code, 1)
        self.assertTrue(any("复盘" in x for x in d["problems"]))

    def test_code_change_after_review_requires_new_review(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        write(self.d, "src/new.py", "x = 1\n")
        code, d = self.de("archive")
        self.assertEqual(code, 1)
        self.assertTrue(any("重新 review" in x for x in d["problems"]))

    def test_archive_record_escapes_table_cells(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "a|b\nc")
        self.de("step", "2", "--status", "in_progress")
        self.de("step", "2", "--status", "done")
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        code, d = self.de("archive", "--apply")
        body = open(os.path.join(self.d, d["archived_to"]), encoding="utf-8").read()
        self.assertIn("a\\|b c", body)
        self.assertEqual(self.de("archive", "--apply")[1].get("already_archived"), True)


class TestValidation(Base):
    """评审 F-06、F-12、F-13 与 P1-02 的计划质量检查。"""

    def test_list_id_reports_error_not_traceback(self):
        self.set_card()
        self.set_plan(st=steps({1: {"id": [1]}}))
        code, d = self.de("check", "plan")
        self.assertEqual(code, 2)
        self.assertIn("id", d["reason"])
        self.assertNotIn("Traceback", json.dumps(d))

    def test_bad_types_report_error(self):
        self.set_card()
        self.set_plan(st=steps({1: {"depends_on": "2", "estimate_h": "4"}}))
        self.assertEqual(self.de("check", "plan")[0], 2)

    def test_conclusion_must_be_enum(self):
        self.set_card(CARD.replace("- 结论：改后做（先业余验证）", "- 结论：我觉得可以做"))
        code, d = self.de("check", "card")
        self.assertEqual(code, 1)
        self.set_card(CARD.replace("- 结论：改后做（先业余验证）", "- 结论：做个调研再说"))
        self.assertEqual(self.de("check", "card")[0], 1)

    def test_stop_loss_needs_structured_fields(self):
        self.set_card(CARD.replace("- 期限：2099-11-30\n", ""))
        code, d = self.de("check", "card")
        self.assertTrue(any("期限" in e for e in d["errors"]))
        self.set_card(CARD.replace("- 期限：2099-11-30", "- 期限：下个月"))
        self.assertEqual(self.de("check", "card")[0], 1)

    def test_kill_deadline_escalates(self):
        self.ready()
        self.set_card(CARD.replace("2099-11-30", "2020-01-01"))
        st = self.de("status")[1]
        self.assertTrue(any("止损期限" in e for e in st["escalations"]))

    def test_criteria_coverage(self):
        self.set_card()
        self.set_plan(st=steps({2: {"covers": []}}))
        code, d = self.de("check", "plan")
        self.assertEqual(code, 0)
        self.assertTrue(any("没有任何步骤覆盖" in w for w in d["warnings"]))
        self.set_plan(risk="high", st=steps({2: {"covers": []}}))
        self.assertEqual(self.de("check", "plan")[0], 1)

    def test_dependency_cycle(self):
        self.set_card()
        self.set_plan(st=steps({1: {"depends_on": [2]}}))
        code, d = self.de("check", "plan")
        self.assertTrue(any("循环" in e for e in d["errors"]))

    def test_template_card_fails(self):
        code, d = self.de("check", "card")
        self.assertEqual(code, 1)

    def test_init_is_idempotent(self):
        self.set_card()
        code, d = self.de("init")
        self.assertEqual((code, d["created"]), (0, []))
        self.assertEqual(self.de("check", "card")[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
