"""v4.0.1 独立复审 P1 失败复现/回归；隔离 Git 仓库，不修改真实用户数据。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_de import Base, CARD, RETRO  # noqa: E402
from helpers import AUDIT, call, write  # noqa: E402


class TestV401Regressions(Base):
    def test_v401_01_untracked_content_changes_fingerprint(self):
        write(self.d, "dynamic.txt", "ONE")
        a = self.de("status")[1]["fingerprint"]
        write(self.d, "dynamic.txt", "TWO")
        b = self.de("status")[1]["fingerprint"]
        self.assertNotEqual(a, b)
        self.assertEqual(call(AUDIT, self.d)[1]["fingerprint"], b)

    def test_v401_01_untracked_content_stales_command(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.de("step", "1", "--status", "done", "--evidence", "records")
        self.de("step", "2", "--status", "in_progress")
        write(self.d, "dynamic.txt", "ONE")
        self.assertEqual(self.de("step", "2", "--status", "done")[0], 0)
        write(self.d, "dynamic.txt", "TWO")
        self.assertIn("2", self.de("status")[1]["stale_evidence_steps"])
        self.assertEqual(self.de("review", "--verdict", "pass")[0], 3)

    def test_v401_02_assumption_invalidates_a(self):
        self.ready()
        self.set_card(CARD.replace("店主愿意付费", "店主不愿意付费"))
        self.assertEqual(self.de("status")[1]["gates"]["A"], "stale")

    def test_v401_03_first_step_invalidates_b(self):
        self.ready()
        p = self.plan()
        p["first_step"] = 2
        write(self.d, ".decision/plan.json", json.dumps(p, ensure_ascii=False))
        self.assertEqual(self.de("status")[1]["gates"]["B"], "stale")

    def test_v401_03_if_then_invalidates_b(self):
        self.ready()
        p = self.plan()
        p["if_then"][0]["then"] = "停止"
        write(self.d, ".decision/plan.json", json.dumps(p, ensure_ascii=False))
        self.assertEqual(self.de("status")[1]["gates"]["B"], "stale")

    def test_v401_04_changed_artifact_blocks_review(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        write(self.d, "proof.txt", "original")
        self.assertEqual(self.de("step", "1", "--status", "done", "--artifact", "proof.txt")[0], 0)
        self.de("step", "2", "--status", "in_progress")
        self.assertEqual(self.de("step", "2", "--status", "done")[0], 0)
        write(self.d, "proof.txt", "changed!")
        self.assertIn("1", self.de("status")[1]["stale_evidence_steps"])
        code, d = self.de("review", "--verdict", "pass")
        self.assertEqual(code, 3, d)
        self.assertIn("1", str(d["problems"]))
        write(self.d, ".decision/retro.md", RETRO)
        self.assertEqual(self.de("archive", "--apply")[0], 3)

    def test_v401_04_missing_artifact_blocks_review(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        write(self.d, "proof.txt", "original")
        self.de("step", "1", "--status", "done", "--artifact", "proof.txt")
        self.de("step", "2", "--status", "in_progress")
        self.de("step", "2", "--status", "done")
        os.remove(os.path.join(self.d, "proof.txt"))
        self.assertEqual(self.de("review", "--verdict", "pass")[0], 3)

    def test_v401_05_forged_external_audit_not_trusted(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        self.assertEqual(self.de("archive", "--apply")[0], 0)
        write(self.d, "broken.md", "[bad](a-nonexistent-file.md)\n")
        fp = self.de("status")[1]["fingerprint"]
        write(self.d, ".decision/closeout-audit.json", json.dumps({
            "summary": {"error": 0, "warn": 0}, "fingerprint": fp,
            "complete": True, "truncated": False,
        }))
        write(self.d, ".decision/closeout-report.md", "# Report\n\nSome sufficiently long report that claims everything is fine.\n")
        code, d = self.de("sync", "--audit-json", self.p("closeout-audit.json"),
                          "--report", self.p("closeout-report.md"))
        self.assertEqual(code, 3, d)
        self.assertTrue(any("审计" in x for x in d["problems"]))


if __name__ == "__main__":
    unittest.main()
