"""4.2：运行时状态与计划分离、gate AB、closeout、多工作区、英文决策卡。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_de import RETRO, Base, read_json, write_json  # noqa: E402
from helpers import AUDIT, DE, ENV, call, commit_all, write  # noqa: E402

CARD_EN = """# Decision card: Orders to PostgreSQL

- Date: 2026-11-16
- Verdict: go with changes (migrate read path first)
- Confidence: medium, based on a dry run against a copy of production data

## Goal
Orders service runs on PostgreSQL with no data loss.

## Success criteria
1. All order tests pass against PostgreSQL [CI job: pg-tests]
2. Row counts match between SQLite and PostgreSQL after migration

## Non-goals
- No schema redesign

## Key assumptions
| # | Assumption | If it is false | Status |
|---|---|---|---|
| A1 | The ORM queries are portable | Rewrite raw SQL first | unverified |

## Stop-loss
- Trigger: migration script still loses rows
- Deadline: 2099-12-31
- Action: stop and keep SQLite

## Escalation
- Max fails: 3
"""

RETRO_EN = ("# Retro\n\n## Expected\nTwo days\n\n## What happened\nThree days\n\n"
            "## Why it differed\nRaw SQL in reports\n")


class TestStateSplit(Base):
    def test_plan_json_holds_structure_only(self):
        self.finish()
        p = self.plan()
        self.assertNotIn("gates", p)
        self.assertEqual(self.state()["steps"]["2"]["status"], "done")
        self.assertIn("A", self.state()["gates"])

    def test_audit_reads_progress_from_state(self):
        self.finish()
        findings = call(AUDIT, self.d)[1]["findings"]
        self.assertTrue(any(f["check"] == "decision" and f["severity"] == "warn" for f in findings), findings)

    def test_forged_runtime_fields_in_plan_json_are_ignored(self):
        self.ready()
        p = self.plan()
        p["steps"][0].update(status="done", evidence=[{"kind": "note", "text": "伪造"}])
        p["review"] = {"verdict": "pass"}
        write_json(self.p("plan.json"), p)
        st = self.de("status")[1]
        self.assertEqual(st["counts"]["done"], 0)
        self.assertEqual(st["stage"], "execute")
        self.assertTrue(any("已忽略" in w for w in st["warnings"]), st["warnings"])

    def test_hand_edited_state_is_detected(self):
        self.finish()
        state = self.state()
        state["steps"]["1"]["evidence"][0]["text"] = "改过的证据"
        write_json(self.p("state.json"), state)
        st = self.de("status")[1]
        self.assertTrue(any("de.py 之外被修改" in w for w in st["warnings"]), st["warnings"])

    def test_legacy_workspace_migrates_on_next_write(self):
        self.ready()
        state, plan = self.state(), self.plan()
        for s in plan["steps"]:
            s.update(state["steps"][str(s["id"])])
        plan.update(gates=state["gates"], last_event=state["last_event"])
        write_json(self.p("plan.json"), plan)
        os.remove(self.p("state.json"))
        st = self.de("status")[1]
        self.assertEqual(st["gates"], {"A": "valid", "B": "valid"})
        self.assertTrue(any("4.2 之前" in w for w in st["warnings"]))
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 0)
        self.assertTrue(os.path.exists(self.p("state.json")))
        self.assertNotIn("gates", self.plan())
        self.assertEqual(self.de("status")[1]["gates"]["B"], "valid")


class TestGateAB(Base):
    def test_standard_tier_confirms_both_at_once(self):
        self.set_card()
        self.set_plan()
        d = self.confirm("gate", "AB")
        self.assertEqual(d["gate"], "AB")
        self.assertEqual(self.de("status")[1]["gates"], {"A": "valid", "B": "valid"})
        self.assertEqual(self.de("step", "1", "--status", "in_progress")[0], 0)

    def test_high_risk_requires_separate_gates(self):
        self.set_card()
        self.set_plan(risk="high")
        code, d = self.de("gate", "AB")
        self.assertEqual(code, 2, d)


class TestCloseout(Base):
    def test_preview_then_apply_archives_and_syncs(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        code, d = self.de("closeout", "--report", self.p("closeout-report.md"))
        self.assertEqual(code, 1, d)                      # 报告还没写
        write(self.d, ".decision/closeout-report.md", "# 收尾报告\n\n静态审计无问题；README 与命令已核对，运行验证见上。\n")
        code, d = self.de("closeout", "--report", self.p("closeout-report.md"))
        self.assertEqual(code, 0, d)
        self.assertTrue(d["closeout_preview"])
        self.assertFalse(os.path.exists(self.p("ARCHIVED")))
        code, d = self.de("closeout", "--report", self.p("closeout-report.md"), "--apply")
        self.assertEqual(code, 0, d)
        self.assertTrue(read_json(self.p("ARCHIVED"))["synced"])
        self.assertEqual(self.de("status")[1]["stage"], "ready-to-purge")


class TestWorkspaces(Base):
    def test_list_and_fingerprint_ignore_other_workspaces(self):
        commit_all(self.d)
        self.assertEqual(self.de("init", "--dir", ".decision-b")[0], 0)
        listed = [w["dir"] for w in self.de("list")[1]["workspaces"]]
        self.assertEqual(listed, [".decision", ".decision-b"])
        fp = self.de("status")[1]["fingerprint"]
        write(self.d, ".decision-b/progress.md", "另一件事的进度\n")
        self.assertEqual(self.de("status")[1]["fingerprint"], fp)
        self.assertEqual(call(AUDIT, self.d)[1]["fingerprint"], fp)
        self.assertIn(".decision-b", self.de("status")[1]["other_workspaces"])

    def test_env_var_selects_workspace(self):
        self.de("init", "--dir", ".decision-b")
        ENV["DE_WORKSPACE"] = ".decision-b"
        try:
            code, d = call(DE, self.d, "status")
        finally:
            ENV.pop("DE_WORKSPACE")
        self.assertEqual(code, 0, d)
        self.assertEqual(d["other_workspaces"], [".decision"])


class TestEnglishCard(Base):
    def setUp(self):
        super().setUp()
        from helpers import rmtree
        rmtree(self.p())
        self.assertEqual(self.de("init", "--lang", "en", "--name", "Orders")[0], 0)

    def test_english_template_and_card(self):
        code, d = self.de("check", "card")
        self.assertEqual(code, 1)                                          # 模板未填
        self.set_card(CARD_EN)
        code, d = self.de("check", "card")
        self.assertEqual(code, 0, d)
        self.assertEqual(d["verdict"], "改后做")
        self.set_plan()
        self.confirm("gate", "AB")
        for sid, ev in (("1", ["--evidence", "dry run notes"]), ("2", [])):
            self.de("step", sid, "--status", "in_progress")
            self.assertEqual(self.de("step", sid, "--status", "done", *ev)[0], 0)
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO_EN)
        code, d = self.de("archive", "--outcome", "done", "--apply")
        self.assertEqual(code, 0, d)
        with open(os.path.join(self.d, d["archived_to"]), encoding="utf-8") as f:
            body = f.read()
        self.assertTrue(body.startswith("# Decision record: Orders to PostgreSQL"))
        self.assertIn("- Outcome: done", body)


if __name__ == "__main__":
    unittest.main()
