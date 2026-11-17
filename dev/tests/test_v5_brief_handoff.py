#!/usr/bin/env python3
"""v5：status --brief（会话钩子用）与 handoff（只读交接摘要）。"""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import DE, ENV, commit_all, rmtree, write  # noqa: E402
from test_de import Base, CARD, RETRO, steps, read_json, write_json  # noqa: E402


def raw(cwd, *args, env=None):
    r = subprocess.run([sys.executable, DE] + list(args), cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env or ENV, timeout=120)
    return r.returncode, r.stdout, r.stderr


def snapshot(d):
    files = {}
    for name in sorted(os.listdir(d)):
        with open(os.path.join(d, name), "rb") as f:
            files[name] = f.read()
    return files


class TestBrief(Base):
    def brief(self, *extra, cwd=None, env=None):
        return raw(cwd or self.d, "status", "--brief", *extra, env=env)

    def test_brief_no_workspace_prints_nothing_exit0(self):
        rmtree(self.p())
        code, outp, err = self.brief()
        self.assertEqual((code, outp), (0, ""), err)

    def test_brief_non_git_without_marker_silent_with_marker_prints(self):
        d = os.path.realpath(tempfile.mkdtemp())
        try:
            self.assertEqual(raw(d, "status", "--brief")[:2], (0, ""))
            raw(d, "init", "--name", "非 git")
            code, outp, _ = raw(d, "status", "--brief")
            self.assertEqual(code, 0)
            self.assertTrue(outp.startswith("[de] .decision"), outp)
        finally:
            rmtree(d, ignore_errors=True)

    def test_brief_env_workspace_outside_project_silent(self):
        env = dict(ENV, DE_WORKSPACE=os.path.dirname(self.d))
        self.assertEqual(self.brief(env=env)[:2], (0, ""))

    def test_brief_corrupt_plan_one_line_exit0(self):
        write(self.d, ".decision/plan.json", "{")
        code, outp, _ = self.brief()
        self.assertEqual(code, 0)
        lines = outp.strip().splitlines()
        self.assertEqual(len(lines), 1, outp)
        self.assertTrue(lines[0].startswith("[de]"))

    def test_brief_line_and_char_limits(self):
        long = steps()
        many = [dict(long[0], id=i, title="很长的步骤标题" * 20, depends_on=[]) for i in range(1, 41)]
        self.ready(st=many)
        for i in range(8):
            self.de("init", "--dir", ".decision-w%d" % i)
        code, outp, _ = self.brief()
        self.assertEqual(code, 0)
        self.assertLessEqual(len(outp.rstrip("\n").splitlines()), 15)
        self.assertLessEqual(len(outp.rstrip("\n")), 1500)
        self.assertIn("等共 8 个", outp)

    def test_brief_contains_stage_and_same_next_as_status(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        st = self.de("status")[1]
        outp = self.brief()[1]
        self.assertIn("阶段 execute", outp)
        self.assertIn(st["next"]["cmd"], outp)

    def test_brief_writes_nothing(self):
        self.ready()
        before = snapshot(self.p())
        self.brief()
        self.assertEqual(before, snapshot(self.p()))

    def test_brief_english_workspace_is_english(self):
        self.de("init", "--dir", ".decision-en", "--lang", "en")
        outp = self.brief("--dir", ".decision-en")[1]
        self.assertIn("stage direction", outp)
        self.assertIn("next:", outp)

    def test_brief_lists_unselected_workspaces(self):
        rmtree(self.p())
        self.de("init", "--dir", ".decision-b")
        commit_all(self.d)
        outp = self.brief()[1]
        self.assertIn(".decision-b", outp)

    def test_brief_fingerprint_error_degrades(self):
        self.finish()
        with open(os.path.join(self.d, "big.bin"), "wb") as f:
            f.truncate(33 * 1024 * 1024)
        code, outp, _ = self.brief()
        self.assertEqual(code, 0)
        self.assertIn("代码指纹不可用", outp)


class TestHandoff(Base):
    def test_handoff_markdown_sections_zh(self):
        self.ready()
        code, outp, _ = raw(self.d, "handoff")
        self.assertEqual(code, 0)
        for h in ("# 交接摘要：测试项目", "## 步骤", "## 升级", "## 关键假设", "## 成功标准覆盖", "## 最近事件",
                  "## 下一步", "## 相关文件"):
            self.assertIn(h, outp)

    def test_handoff_markdown_sections_en(self):
        self.de("init", "--dir", ".decision-en", "--lang", "en", "--name", "Demo")
        outp = raw(self.d, "handoff", "--dir", ".decision-en")[1]
        for h in ("# Handoff: Demo", "## Steps", "## Key assumptions", "## Next", "## Files"):
            self.assertIn(h, outp)

    def test_handoff_json_shape_and_freshness(self):
        self.finish()
        h = self.de("handoff", "--json")[1]
        for k in ("stage", "gates", "steps", "assumptions", "events", "next", "files"):
            self.assertIn(k, h)
        fresh = {s["id"]: s["freshness"] for s in h["steps"]}
        self.assertEqual(fresh, {1: "unverified", 2: "fresh"})
        self.assertLessEqual(len(h["events"]), 5)
        self.assertEqual(h["next"], self.de("status")[1]["next"])

    def test_handoff_marks_stale_after_commit(self):
        self.finish()
        commit_all(self.d)
        h = self.de("handoff", "--json")[1]
        self.assertEqual({s["id"]: s["freshness"] for s in h["steps"]}[2], "stale")

    def test_handoff_lists_assumption_status_and_tests(self):
        self.ready(st=steps({1: {"tests_assumption": "A1"}}))
        self.set_card(CARD.replace("| 未验证 |", "| 已证实 |"))
        a = self.de("handoff", "--json")[1]["assumptions"][0]
        self.assertEqual((a["id"], a["status"]), ("A1", "已证实"))
        self.assertEqual(a["tested_by"][0]["step"], 1)

    def test_handoff_writes_nothing_and_gives_paths_not_contents(self):
        self.ready()
        before = snapshot(self.p())
        outp = raw(self.d, "handoff")[1]
        self.assertEqual(before, snapshot(self.p()))
        self.assertIn(".decision/decision-card.md", outp)
        self.assertNotIn("三个月内确认是否有人付费", outp)

    def test_handoff_archived_workspace(self):
        self.finish()
        self.confirm("review", "--verdict", "pass")
        write(self.d, ".decision/retro.md", RETRO)
        self.assertEqual(self.de("archive", "--apply")[0], 0)
        h = self.de("handoff", "--json")[1]
        self.assertEqual(h["stage"], "archived")
        self.assertTrue(h["files"]["record"].startswith("docs/decisions/"))


class TestFingerprintOnce(Base):
    """进程内运行 main()，统计 fingerprint 调用次数：一次调用只算一次指纹（brief 执行期一次都不算）。"""

    def count(self, *argv):
        spec = importlib.util.spec_from_file_location("de_inproc", DE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        calls = []
        real = mod.fingerprint
        mod.fingerprint = lambda ctx: calls.append(1) or real(ctx)
        old_cwd, old_argv = os.getcwd(), sys.argv
        os.chdir(self.d)
        sys.argv = ["de.py"] + list(argv)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    mod.main()
                except SystemExit:
                    pass
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
        return len(calls)

    def test_read_only_views_compute_fingerprint_once(self):
        self.finish()
        for argv in (["status"], ["handoff"], ["handoff", "--json"], ["coverage"], ["status", "--brief"]):
            self.assertEqual(self.count(*argv), 1, argv)

    def test_brief_execute_stage_skips_fingerprint(self):
        self.ready()
        self.de("step", "1", "--status", "in_progress")
        self.assertEqual(self.count("status", "--brief"), 0)


if __name__ == "__main__":
    unittest.main()
