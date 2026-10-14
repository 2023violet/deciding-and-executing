#!/usr/bin/env python3
"""closing-out/scripts/audit.py 回归与对抗测试。用法: python3 -m unittest discover -s dev/tests"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AUDIT, DE, call, commit_all, init_repo, write  # noqa: E402


def checks(data, severity=None):
    return [(f["check"], f.get("file")) for f in data["findings"] if severity in (None, f["severity"])]


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        init_repo(self.d)
        write(self.d, "package.json", '{"scripts": {"dev": "vite", "test": "vitest"}}')
        write(self.d, "src/app.ts", "export const fetchUser = 1\n")
        write(self.d, "README.md", "# Demo\n运行 `npm run dev`。\n")
        write(self.d, "AGENTS.md", "# Rules\n- 测试：`npm test`\n- 代码在 `src/app.ts`\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def audit(self, *args):
        return call(AUDIT, self.d, *args)

    # ---- 基础
    def test_clean_repo_passes_and_states_limits(self):
        commit_all(self.d)
        code, d = self.audit()
        self.assertEqual(code, 0, d["findings"])
        self.assertTrue(d["complete"])
        self.assertEqual(d["evidence_level"], "static")
        self.assertTrue(any("语义" in x for x in d["limits"]))

    def test_read_only(self):
        write(self.d, "PLAN.md", "x")
        commit_all(self.d)
        before = sorted(os.listdir(self.d))
        self.audit("--rename", "a=b")
        self.assertEqual(before, sorted(os.listdir(self.d)))

    def test_truncated_is_not_a_pass(self):
        for i in range(5):                       # 只有 warn 级残留，没有 error：唯一的问题是截断
            write(self.d, "debug_%d.py" % i, "x")
        commit_all(self.d)
        code, d = self.audit("--max-findings", "2")
        self.assertEqual(d["summary"]["error"], 0)
        self.assertEqual(code, 1)
        self.assertFalse(d["complete"])
        self.assertFalse(d["ok"])
        self.assertEqual(self.audit()[0], 0)    # 不截断时同样的仓库是通过的

    # ---- 链接与命令
    def test_dead_link_and_code_block_ignored(self):
        write(self.d, "README.md", "# D\n[a](docs/missing.md)\n```\n[b](also/missing.md)\n```\n`[c](x.md)`\n[ok](src/app.ts)\n")
        commit_all(self.d)
        code, d = self.audit()
        dead = [f["message"] for f in d["findings"] if f["check"] == "dead-links"]
        self.assertEqual(len(dead), 1)
        self.assertIn("docs/missing.md", dead[0])

    def test_rule_refs(self):
        write(self.d, "AGENTS.md", "- `npm run e2e`\n- `src/gone.ts`\n")
        write(self.d, "CLAUDE.md", "@AGENTS.md\n@docs/nope.md\n")
        commit_all(self.d)
        _, d = self.audit()
        msgs = " ".join(f["message"] for f in d["findings"] if f["check"] == "rule-refs")
        for x in ("e2e", "src/gone.ts", "docs/nope.md"):
            self.assertIn(x, msgs)

    def test_dot_directory_paths_not_mangled(self):
        write(self.d, ".github/workflows/ci.yml", "x")
        write(self.d, "AGENTS.md", "- CI 在 `.github/workflows/ci.yml`\n- 也可写 `./src/app.ts`\n")
        commit_all(self.d)
        _, d = self.audit()
        self.assertNotIn("rule-refs", [c for c, _ in checks(d)])

    def test_doc_commands_checked(self):
        write(self.d, "README.md", "# D\n测试：`npm run e2e`\n")
        commit_all(self.d)
        _, d = self.audit()
        self.assertIn(("doc-commands", "README.md"), checks(d, "error"))

    def test_npm_run_test_requires_script(self):
        write(self.d, "package.json", '{"scripts": {"dev": "vite"}}')
        write(self.d, "README.md", "# D\n`npm run test`\n")
        write(self.d, "AGENTS.md", "# r\n")
        commit_all(self.d)
        _, d = self.audit()
        self.assertIn(("doc-commands", "README.md"), checks(d, "error"))

    # ---- 规则链
    def test_rules_chain_requires_import(self):
        write(self.d, "CLAUDE.md", "# Claude\n- plan mode\n")
        commit_all(self.d)
        _, d = self.audit()
        self.assertIn(("rules-chain", "CLAUDE.md"), checks(d, "warn"))
        write(self.d, "CLAUDE.md", "@AGENTS.md\n\n## Claude\n- plan mode\n")
        _, d = self.audit()
        self.assertNotIn(("rules-chain", "CLAUDE.md"), checks(d))

    def test_effective_chain_not_global_sum(self):
        big = "- 规则\n" * 1500          # 约 15 KB
        write(self.d, "AGENTS.md", big)
        write(self.d, "src/AGENTS.md", big)
        write(self.d, "tests/AGENTS.md", big)
        commit_all(self.d)
        code, d = self.audit()
        self.assertEqual(code, 0, [f for f in d["findings"] if f["severity"] == "error"])
        write(self.d, "src/deep/AGENTS.md", big)       # 根 + src + src/deep 超过 32 KiB
        commit_all(self.d)
        code, d = self.audit()
        self.assertEqual(code, 1)
        self.assertIn(("rules-chain", "src/deep/AGENTS.md"), checks(d, "error"))
        self.assertEqual(d["inventory"]["rule_chains"][0]["dir"], "src/deep")

    def test_override_replaces_agents_in_chain(self):
        write(self.d, "AGENTS.md", "- 规则\n" * 6000)
        write(self.d, "AGENTS.override.md", "- 临时覆盖\n")
        commit_all(self.d)
        _, d = self.audit()
        self.assertNotIn("error", [f["severity"] for f in d["findings"] if f["check"] == "rules-chain"])
        self.assertIn(("rules-chain", "AGENTS.override.md"), checks(d, "warn"))

    # ---- 旧名字
    def test_stale_names_skip_history(self):
        write(self.d, "README.md", "# D\n调用 getUser。\n")
        write(self.d, "CHANGELOG.md", "- 把 getUser 改名为 fetchUser\n")
        write(self.d, "docs/decisions/2026-01-01-x.md", "当时用 getUser\n")
        commit_all(self.d)
        _, d = self.audit("--rename", "getUser=fetchUser")
        self.assertEqual([f.get("file") for f in d["findings"] if f["check"] == "stale-names"], ["README.md"])

    def test_rename_where_new_is_prefix_of_old(self):
        write(self.d, "README.md", "# D\n调用 fetchUserData。\n")
        commit_all(self.d)
        _, d = self.audit("--rename", "fetchUserData=fetchUser")
        self.assertIn(("stale-names", "README.md"), checks(d, "error"))

    def test_rename_where_old_is_prefix_of_new(self):
        write(self.d, "README.md", "# D\n调用 getUserById。\n")
        commit_all(self.d)
        _, d = self.audit("--rename", "getUser=getUserById")
        self.assertNotIn(("stale-names", "README.md"), checks(d, "error"))

    # ---- 残留与文件名
    def test_residue_and_odd_filenames(self):
        write(self.d, "PLAN.md", "- [x] 改 getUser\n")
        write(self.d, "src/app_old.ts", "x")
        commit_all(self.d)
        write(self.d, "debug thing \"q\" 调试.py", "x")
        write(self.d, "docs/新 文件.md", "# x\n")
        code, d = self.audit("--rename", "getUser=fetchUser")
        self.assertNotIn(("stale-names", "PLAN.md"), checks(d))
        warn = sorted(f for c, f in checks(d, "warn") if c == "residue")
        self.assertEqual(warn, ["PLAN.md", "src/app_old.ts"])
        untracked = sorted(f for c, f in checks(d, "info") if c == "residue")
        self.assertEqual(untracked, ["debug thing \"q\" 调试.py", "docs/新 文件.md"])
        self.assertIn("docs/新 文件.md", d["inventory"]["changed_files"])

    def test_exclude(self):
        write(self.d, "fixtures/README.md", "[x](missing.md)\n")
        commit_all(self.d)
        self.assertEqual(self.audit()[0], 1)
        self.assertEqual(self.audit("--exclude", "fixtures/*")[0], 0)

    def test_changed_files_on_root_commit(self):
        d2 = os.path.realpath(tempfile.mkdtemp())
        try:
            from helpers import git
            git(d2, "init", "-q")
            write(d2, "README.md", "# x\n")
            commit_all(d2)
            _, d = call(AUDIT, d2)
            self.assertIn("README.md", d["inventory"]["changed_files"])
        finally:
            shutil.rmtree(d2)

    # ---- 与 deciding-and-executing 的接口
    def test_decision_workspace_detection_and_exclusion(self):
        commit_all(self.d)
        call(DE, self.d, "init")
        write(self.d, ".decision/decision-card.md", "[死链](nowhere.md)\n")   # 工作区内容不参与文档检查
        _, d = self.audit()
        self.assertEqual(d["inventory"]["decision_workspaces"], [".decision"])
        self.assertNotIn("dead-links", [c for c, _ in checks(d)])
        self.assertIn(("decision", ".decision"), checks(d, "info"))

    def test_fingerprint_matches_de_py(self):
        commit_all(self.d)
        call(DE, self.d, "init")
        write(self.d, "README.md", "# changed\n")
        _, a = self.audit()
        _, s = call(DE, self.d, "status")
        self.assertIsNotNone(a["fingerprint"])
        self.assertEqual(a["fingerprint"], s["fingerprint"])
        write(self.d, ".decision/progress.md", "工作区内的变化不影响指纹\n")
        self.assertEqual(self.audit()[1]["fingerprint"], a["fingerprint"])

    # ---- 参数
    def test_bad_args(self):
        self.assertEqual(call(AUDIT, self.d, "--rename", "nonsense")[0], 2)
        self.assertEqual(call(AUDIT, self.d, "--max-findings", "0")[0], 2)

    def test_non_git_dir(self):
        d2 = tempfile.mkdtemp()
        try:
            write(d2, "README.md", "# x\n")
            code, d = call(AUDIT, d2)
            self.assertEqual(code, 0)
            self.assertFalse(d["inventory"]["git"])
            self.assertIsNone(d["fingerprint"])
        finally:
            shutil.rmtree(d2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
