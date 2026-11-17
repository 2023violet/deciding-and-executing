#!/usr/bin/env python3
"""v5：review --independent-report 关联工作区里的独立复核报告，报告事后被改则审查结论失效。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import commit_all, write  # noqa: E402
from test_de import Base, RETRO, read_json  # noqa: E402

REPORT = "# 独立复核报告\n\n| 1 | 自己运行了测试命令 | PASS | 无 |\n| 2 | 退出码 0 | PASS | 无 |\n"


class TestIndependentReport(Base):
    def reviewed(self):
        self.finish()
        write(self.d, ".decision/independent-review.md", REPORT)
        self.confirm("review", "--verdict", "pass", "--independent-report")

    def test_review_records_independent_report_hash(self):
        self.reviewed()
        rep = self.state()["review"]["independent_report"]
        self.assertEqual(rep["path"], ".decision/independent-review.md")
        self.assertEqual(len(rep["sha"]), 16)

    def test_missing_or_tiny_report_refused(self):
        self.finish()
        code, d = self.de("review", "--verdict", "pass", "--independent-report")
        self.assertEqual(code, 2)
        write(self.d, ".decision/independent-review.md", "短")
        self.assertEqual(self.de("review", "--verdict", "pass", "--independent-report")[0], 2)

    def test_report_symlink_refused(self):
        self.finish()
        write(self.d, "elsewhere.md", REPORT)
        try:
            os.symlink(os.path.join(self.d, "elsewhere.md"), self.p("independent-review.md"))
        except (OSError, NotImplementedError):
            self.skipTest("无权限创建符号链接")
        self.assertEqual(self.de("review", "--verdict", "pass", "--independent-report")[0], 2)

    def test_changed_report_invalidates_review_and_blocks_archive(self):
        self.reviewed()
        write(self.d, ".decision/retro.md", RETRO)
        self.assertEqual(self.de("status")[1]["stage"], "closeout")
        write(self.d, ".decision/independent-review.md", REPORT + "\n事后补了一句\n")
        st = self.de("status")[1]
        self.assertEqual(st["stage"], "review")
        code, d = self.de("archive")
        self.assertTrue(any("独立复核报告" in p for p in d["problems"]), d)

    def test_record_mentions_report_path(self):
        self.reviewed()
        write(self.d, ".decision/retro.md", RETRO)
        code, d = self.de("archive", "--apply")
        self.assertEqual(code, 0, d)
        with open(os.path.join(self.d, d["archived_to"]), encoding="utf-8") as f:
            self.assertIn("独立复核报告：.decision/independent-review.md", f.read())

    def test_purge_accepts_independent_review_file(self):
        self.reviewed()
        write(self.d, ".decision/retro.md", RETRO)
        self.assertEqual(self.de("archive", "--apply")[0], 0)
        write(self.d, ".decision/closeout-report.md", "# 收尾报告\n\n文档与代码一致，静态审计 error 0，无需修改。\n")
        self.assertEqual(self.de("sync", "--report", self.p("closeout-report.md"))[0], 0)
        commit_all(self.d)
        code, d = self.de("purge")
        self.assertEqual(code, 3)
        self.assertTrue(d.get("needs_confirmation"), d)          # 不是"未知文件"拒绝

    def test_review_without_report_unchanged(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        self.assertNotIn("independent_report", self.state()["review"])


if __name__ == "__main__":
    unittest.main()
