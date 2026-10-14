#!/usr/bin/env python3
"""audit.py — closing-out 的只读审计脚本（仅用标准库，Python 3.8+；有 git 时检查更完整）。

找出项目里"文档、规则文件、工作区"与现状不一致、且能被机械检查出来的地方。
只读：不修改、不删除任何文件。

能力边界（报告里必须照实说明）：
  本脚本只做【静态审计】——链接、路径、命令、旧名字、规则文件结构、残留文件。
  它不理解文档语义：README 说"使用 SQLite"而代码已换成 PostgreSQL，它发现不了。
  因此 error 0 只表示"已实现的规则没有发现问题"，不表示"文档正确"。
  变更影响分析、源码事实核查、运行验证，需要按 SKILL.md 的流程由人或 Agent 完成。

用法:
  python3 scripts/audit.py [--root .] [--base REF] [--rename OLD=NEW ...] [--exclude GLOB ...] [--max-findings 200]

参数:
  --root          项目根目录（默认当前目录；在 git 仓库内会自动定位到仓库根）
  --base          对比的 git 基准（分支、标签或提交）。省略时：未提交的改动 + 最近一次提交
  --rename        本次改过的名字 old=new，可重复；用来搜索旧名字残留
  --exclude       不参与文档检查的路径模式（fnmatch），可重复，例如 'dev/eval-runs/*'
  --max-findings  最多输出多少条发现（默认 200）。被截断时 complete=false，结果不能当作通过

检查项（check 字段）:
  rules-chain      每个目录的有效规则链（Codex：从仓库根到该目录，每层一个 AGENTS 文件）是否超出
                   32 KiB；CLAUDE.md 与 AGENTS.md 并存却没有导入；CLAUDE.md 超过 200 行；
                   AGENTS.override.md 存在；CLAUDE.local.md 未被忽略
  rule-refs        规则文件里的 @导入、路径、npm/make 命令是否存在
  doc-commands     README 与 docs 里写的 npm/make 命令是否存在
  dead-links       Markdown 相对链接指向不存在的文件（忽略代码块）
  stale-names      --rename 给出的旧名字残留（跳过 CHANGELOG、决策记录等历史文件）
  duplicate-lines  同一句较长的话出现在多个文档里
  residue          计划草稿、调试脚本、旧副本、未跟踪文件等残留候选
  decision         deciding-and-executing 的工作区状态（含 .de-workspace 标记的目录）

输出: JSON 写到 stdout（含 fingerprint、complete、evidence_level），摘要写到 stderr。
退出码: 0 无 error 且输出完整；1 有 error 或输出被截断；2 用法错误。

示例:
  python3 scripts/audit.py
  python3 scripts/audit.py --base main --rename getUser=fetchUser --exclude 'dev/fixtures/*'
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import unquote

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             "vendor", "target", ".tox", ".mypy_cache", ".pytest_cache", "coverage"}
HISTORY_GLOBS = ["CHANGELOG*", "HISTORY*", "docs/decisions/*", "docs/adr/*", "*.lock"]
RESIDUE_NAME_GLOBS = [
    ("PLAN.md", "一次性计划草稿"), ("TODO.md", "临时待办"), ("NOTES.md", "临时笔记"),
    ("*_old*", "旧副本"), ("*-old*", "旧副本"), ("*_bak*", "备份副本"), ("*.bak", "备份副本"),
    ("*_backup*", "备份副本"), ("*.orig", "合并冲突残留"), ("*.rej", "补丁残留"),
    ("* copy*", "复制副本"), ("*_copy*", "复制副本"), ("scratch*", "草稿"), ("debug_*", "调试脚本"),
    ("tmp_*", "临时文件"), ("*.tmp", "临时文件"),
]
MARKER = ".de-workspace"
CLAUDE_MD_LINE_TARGET = 200          # Claude Code 文档建议每个 CLAUDE.md 少于 200 行
CODEX_DOC_MAX_BYTES = 32 * 1024      # Codex project_doc_max_bytes 默认 32 KiB（项目级，不含 ~/.codex）
MIN_DUP_LEN = 40                     # 短于此长度的重复行通常是模板句式
LIMITS = [
    "静态审计：只检查链接、路径、命令、旧名字、规则文件结构与残留文件",
    "不理解文档语义：文档描述的行为是否仍与代码一致，需要按路由表做源码事实核查",
    "不运行文档里的命令：命令能否真正跑通，需要运行验证",
    "命令检查只覆盖 package.json 的 scripts 与 Makefile 目标",
    "规则链大小只计算仓库内文件，不含 ~/.codex 等全局规则",
]


def sh(args, cwd):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, timeout=60)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, b""


def zsplit(b):
    return [x.decode("utf-8", "surrogateescape") for x in b.split(b"\0") if x]


def porcelain_z(b):
    """解析 git status --porcelain=v1 -z：返回 [(XY, path)]；重命名项的旧路径会被跳过。"""
    items, parts, i = [], b.split(b"\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, path = e[:2].decode(), e[3:].decode("utf-8", "surrogateescape")
        items.append((xy, path))
        if "R" in xy or "C" in xy:
            i += 1
    return items


class Audit:
    def __init__(self, root, base, renames, excludes, limit):
        self.root, self.base, self.renames, self.excludes, self.limit = root, base, renames, excludes, limit
        self.findings = []
        self.git = sh(["git", "rev-parse", "--is-inside-work-tree"], root)[0] == 0

    def add(self, check, severity, message, file=None, line=None, suggestion=None):
        self.findings.append({k: v for k, v in dict(check=check, severity=severity, file=file, line=line,
                                                     message=message, suggestion=suggestion).items() if v is not None})

    # ---------- inventory ----------
    def inventory(self):
        files, self.workspaces = [], []
        for d, dirs, fs in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            rel_d = os.path.relpath(d, self.root)
            if MARKER in fs and rel_d != ".":
                self.workspaces.append(rel_d.replace(os.sep, "/"))
                dirs[:] = []
                continue              # 工作区是过程文件，由 decision 检查单独处理
            for f in fs:
                files.append(os.path.relpath(os.path.join(d, f), self.root).replace(os.sep, "/"))
        self.files = sorted(files)
        self.md = [f for f in self.files if f.lower().endswith(".md") and not self.excluded(f)]
        self.rule_files = [f for f in self.files if os.path.basename(f) in
                           ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md")
                           or f.startswith(".claude/rules/") and f.endswith(".md")]
        inv = {"root": self.root, "git": self.git, "markdown_files": len(self.md), "rule_files": self.rule_files,
               "decision_workspaces": self.workspaces, "excluded_patterns": self.excludes}
        self.untracked = []
        if self.git:
            inv["branch"] = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.root)[1].decode().strip()
            changed = set()
            if self.base:
                code, o = sh(["git", "diff", "-z", "--name-only", self.base + "...HEAD"], self.root)
                if code != 0:
                    print("错误: 无法与基准 %s 比较，请确认分支/提交存在" % self.base, file=sys.stderr)
                    sys.exit(2)
                changed |= set(zsplit(o))
            else:
                changed |= set(zsplit(sh(["git", "diff-tree", "-z", "--root", "--no-commit-id", "--name-only", "-r",
                                          "HEAD"], self.root)[1]))
            st = porcelain_z(sh(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], self.root)[1])
            changed |= set(p for _, p in st)
            self.untracked = [p for xy, p in st if xy == "??"]
            inv["changed_files"] = sorted(c for c in changed if c)
        self.inv = inv

    def excluded(self, f):
        return any(fnmatch.fnmatch(f, g) for g in self.excludes)

    def read(self, rel):
        try:
            with open(os.path.join(self.root, rel), encoding="utf-8") as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            return None

    def fingerprint(self):
        """与 de.py 同协议：未跟踪文件读取内容，忽略文件不覆盖，超限即失败。"""
        if not self.git:
            return None
        code, head = sh(["git", "rev-parse", "HEAD"], self.root)
        head = head.decode().strip() if code == 0 else "NO_COMMIT"
        excl = [":(exclude)%s" % w for w in sorted(self.workspaces)]
        commands = [
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."] + excl,
            ["git", "diff", "HEAD", "--binary", "--", "."] + excl,
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "."] + excl,
        ]
        results = [sh(c, self.root) for c in commands]
        if any(code != 0 for code, _ in results):
            raise RuntimeError("Git 状态或差异读取失败，不能生成可信指纹")
        st, diff, untracked = (v for _, v in results)
        h = hashlib.sha256()
        h.update(st)
        h.update(diff)
        total_bytes = 0
        for name in sorted(n for n in untracked.split(b"\0") if n):
            rel = os.fsdecode(name)
            path = os.path.join(self.root, rel)
            h.update(b"\0path\0" + name + b"\0")
            if os.path.islink(path):
                h.update(b"symlink\0" + os.fsencode(os.readlink(path)))
            else:
                size = os.path.getsize(path)
                total_bytes += size
                if size > 32 * 1024 * 1024 or total_bytes > 128 * 1024 * 1024:
                    raise RuntimeError("未跟踪文件超出单文件 32 MiB / 总量 128 MiB 上限：%s" % rel)
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
        return head[:12] + ("" if not st else "+" + h.hexdigest()[:12])

    # ---------- checks ----------
    def check_rules_chain(self):
        dirs = sorted({os.path.dirname(f) for f in self.files
                       if os.path.basename(f) in ("AGENTS.md", "AGENTS.override.md")})
        chains = []
        for d in dirs:
            parts, chain, cur = ([] if d == "" else d.split("/")), [], ""
            for depth in range(len(parts) + 1):
                cur = "/".join(parts[:depth])
                for name in ("AGENTS.override.md", "AGENTS.md"):
                    f = (cur + "/" + name) if cur else name
                    if f in self.files and os.path.getsize(os.path.join(self.root, f)) > 0:
                        chain.append(f)
                        break
            size = sum(os.path.getsize(os.path.join(self.root, f)) for f in chain)
            chains.append({"dir": d or ".", "bytes": size, "files": chain})
            if size > CODEX_DOC_MAX_BYTES:
                self.add("rules-chain", "error", "在 %s 下工作时，Codex 加载的规则链合计 %d 字节，超过默认 32 KiB，超出部分会被丢弃"
                         % (d or "仓库根目录", size), chain[-1], suggestion="压缩规则，或把只在某目录有效的规则下放到该目录")
            ov = (d + "/" if d else "") + "AGENTS.override.md"
            if ov in self.files:
                self.add("rules-chain", "warn", "存在 AGENTS.override.md：Codex 会用它代替同目录的 AGENTS.md", ov,
                         suggestion="确认这是有意的临时覆盖；不需要时合并回 AGENTS.md 后移除")
        self.inv["rule_chains"] = sorted(chains, key=lambda c: -c["bytes"])[:10]
        for f in self.files:
            if os.path.basename(f) != "CLAUDE.md":
                continue
            d = os.path.dirname(f)
            if d.endswith(".claude"):
                d = os.path.dirname(d)
            agents = (d + "/" if d else "") + "AGENTS.md"
            full = os.path.join(self.root, f)
            if agents in self.files:
                linked = os.path.islink(full) and os.path.realpath(full) == os.path.realpath(os.path.join(self.root, agents))
                if not linked and not re.search(r"(?m)^\s*@\.?/?(\.\./)?AGENTS\.md\b", self.read(f) or ""):
                    self.add("rules-chain", "warn", "%s 与 %s 并存，但 CLAUDE.md 没有导入 AGENTS.md：Claude Code 只读 CLAUDE.md，"
                             "Codex 只读 AGENTS.md，两边规则会各自漂移" % (f, agents), f,
                             suggestion="以 AGENTS.md 为唯一规则源，在 CLAUDE.md 第一行写 @AGENTS.md，下方只放 Claude 专属内容")
            t = self.read(f)
            if t is not None and t.count("\n") > CLAUDE_MD_LINE_TARGET:
                self.add("rules-chain", "warn", "%s 有 %d 行，超过建议的 %d 行，遵循度会下降"
                         % (f, t.count("\n"), CLAUDE_MD_LINE_TARGET), f,
                         suggestion="只留下一个 Agent 不知道就会做错的规则；按目录拆到 .claude/rules/ 或子目录")
        for f in self.files:
            if os.path.basename(f) == "CLAUDE.local.md" and self.git \
                    and sh(["git", "check-ignore", "-q", f], self.root)[0] != 0:
                self.add("rules-chain", "warn", "%s 是个人配置，但没有被 .gitignore 忽略" % f, f,
                         suggestion="把 CLAUDE.local.md 加入 .gitignore")

    def _package_scripts(self):
        t = self.read("package.json")
        if not t:
            return None
        try:
            s = json.loads(t).get("scripts", {})
            return set(s) if isinstance(s, dict) else None
        except ValueError:
            return None

    def _make_targets(self):
        t = self.read("Makefile")
        return set(re.findall(r"(?m)^([A-Za-z0-9_.-]+)\s*:(?!=)", t)) if t else None

    def _check_commands(self, f, i, code, scripts, targets, check):
        m = re.match(r"(?:npm run|pnpm run|pnpm|yarn|bun run)\s+([\w:.-]+)", code)
        if m and scripts is not None and m.group(1) not in scripts | {"install", "add", "dlx", "exec", "i"}:
            self.add(check, "error", "引用的脚本 %s 不在 package.json 的 scripts 里" % m.group(1), f, i)
        elif re.match(r"npm (test|t)\b", code) and scripts is not None and "test" not in scripts:
            self.add(check, "error", "引用了 npm test，但 package.json 没有 test 脚本", f, i)
        m = re.match(r"make\s+([\w.-]+)", code)
        if m and targets is not None and m.group(1) not in targets:
            self.add(check, "error", "引用的 make 目标 %s 在 Makefile 里不存在" % m.group(1), f, i)

    @staticmethod
    def _code_spans(text):
        text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        for i, line in enumerate(text.splitlines(), 1):
            yield i, line, [c.strip() for c in re.findall(r"`([^`]+)`", line)]

    def check_rule_refs(self):
        scripts, targets = self._package_scripts(), self._make_targets()
        for f in self.rule_files:
            t = self.read(f)
            if t is None:
                continue
            base = os.path.dirname(f)
            for i, line, codes in self._code_spans(t):
                for imp in re.findall(r"(?:^|\s)@([~\w./-]+\.\w+)", re.sub(r"`[^`]*`", "", line)):
                    if not imp.startswith("~") and not os.path.exists(os.path.join(self.root, base, imp)):
                        self.add("rule-refs", "error", "@导入的文件不存在：%s" % imp, f, i)
                for code in codes:
                    self._check_commands(f, i, code, scripts, targets, "rule-refs")
                    if " " in code or "/" not in code or not re.search(r"\.\w{1,5}$|/$", code) \
                            or re.match(r"[a-z]+://", code) or any(ch in code for ch in "*<>{}$"):
                        continue
                    cand = code[2:] if code.startswith("./") else code
                    if not any(os.path.exists(os.path.normpath(os.path.join(self.root, b, cand))) for b in (base, "")):
                        self.add("rule-refs", "warn", "规则里提到的路径不存在：%s" % code, f, i,
                                 suggestion="更新为现在的路径，或删除这条已失效的规则")

    def check_doc_commands(self):
        scripts, targets = self._package_scripts(), self._make_targets()
        if scripts is None and targets is None:
            return
        rules = set(self.rule_files)
        for f in self.md:
            if f in rules or self.is_history(f) or self.is_residue(f):
                continue
            for i, _, codes in self._code_spans(self.read(f) or ""):
                for code in codes:
                    self._check_commands(f, i, code, scripts, targets, "doc-commands")

    def check_dead_links(self):
        for f in self.md:
            for i, line, _ in self._code_spans(self.read(f) or ""):
                line = re.sub(r"`[^`]*`", "", line)
                for target in re.findall(r"\]\(([^)\s]+)\)", line):
                    if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|#|//", target):
                        continue
                    target = target.split("#")[0].split("?")[0]
                    if target and not os.path.exists(os.path.normpath(os.path.join(self.root, os.path.dirname(f),
                                                                                    unquote(target)))):
                        self.add("dead-links", "error", "链接指向不存在的文件：%s" % target, f, i)

    def is_history(self, f):
        return any(fnmatch.fnmatch(f, g) or fnmatch.fnmatch(os.path.basename(f), g) for g in HISTORY_GLOBS)

    def is_residue(self, f):
        return any(fnmatch.fnmatch(os.path.basename(f), g) for g, _ in RESIDUE_NAME_GLOBS)

    def check_stale_names(self):
        for old, new in self.renames:
            hits = 0
            for f in self.files:
                if self.is_history(f) or self.is_residue(f) or self.excluded(f):
                    continue
                t = self.read(f)
                if not t or old not in t:
                    continue
                for i, line in enumerate(t.splitlines(), 1):
                    masked = line.replace(new, "\0" * len(new)) if new and old in new else line
                    if old in masked:
                        hits += 1
                        self.add("stale-names", "error" if f.lower().endswith(".md") else "warn",
                                 "旧名字 %s 仍在使用（新名字 %s）" % (old, new or "无"), f, i)
            if hits == 0:
                self.add("stale-names", "info", "旧名字 %s 已无残留（历史类文件除外）" % old)

    def check_duplicates(self):
        seen = {}
        for f in self.md:
            if self.is_history(f):
                continue
            t = re.sub(r"```.*?```", "", self.read(f) or "", flags=re.S)
            for line in t.splitlines():
                s = line.strip().lstrip("-*>| ").strip()
                if len(s) >= MIN_DUP_LEN and not s.startswith(("#", "|", "![")):
                    seen.setdefault(s, set()).add(f)
        for s, fs in seen.items():
            if len(fs) > 1:
                self.add("duplicate-lines", "info", "同一句话出现在 %d 个文件：「%s」" % (len(fs), s[:80]),
                         ", ".join(sorted(fs)), suggestion="保留一个权威位置，其余改为链接；中英双语文档的对应句可忽略")

    def check_residue(self):
        for f in self.files:
            if self.excluded(f):
                continue
            name = os.path.basename(f)
            for g, why in RESIDUE_NAME_GLOBS:
                if fnmatch.fnmatch(name, g):
                    self.add("residue", "warn", "残留候选（%s）" % why, f,
                             suggestion="有用的内容并入正式文档；删除前列入候选清单请用户确认")
                    break
        for u in self.untracked:
            if not self.excluded(u) and not any(u.startswith(w + "/") for w in self.workspaces):
                self.add("residue", "info", "未被 git 跟踪的文件", u, suggestion="决定：提交、加入 .gitignore，或列为删除候选")

    def check_decision(self):
        for w in self.workspaces:
            d = os.path.join(self.root, w)
            if os.path.exists(os.path.join(d, "ARCHIVED")):
                try:
                    m = json.load(open(os.path.join(d, "ARCHIVED"), encoding="utf-8"))
                except ValueError:
                    m = {}
                if m.get("synced"):
                    self.add("decision", "warn", "%s 已归档且已同步，等待删除" % w, w,
                             suggestion="提交后运行 de.py purge 预览，用户确认后删除")
                else:
                    self.add("decision", "info", "%s 已归档，知识同步进行中（本次审计即为同步的一部分）" % w, w)
                continue
            try:
                plan = json.load(open(os.path.join(d, "plan.json"), encoding="utf-8"))
                steps = plan.get("steps", []) if isinstance(plan, dict) else []
                if steps and all(isinstance(s, dict) and s.get("status") == "done" for s in steps):
                    self.add("decision", "warn", "%s 的计划已全部完成但尚未归档：决策卡会被当成现行事实读到" % w, w,
                             suggestion="走完 deciding-and-executing 的 review → archive")
                else:
                    self.add("decision", "info", "%s 是进行中的决策工作区，不属于残留" % w, w)
            except (OSError, ValueError):
                self.add("decision", "warn", "%s 存在但 plan.json 无法读取" % w, w)

    def run(self):
        self.inventory()
        for c in [self.check_rules_chain, self.check_rule_refs, self.check_doc_commands, self.check_dead_links,
                  self.check_stale_names, self.check_duplicates, self.check_residue, self.check_decision]:
            c()
        order = {"error": 0, "warn": 1, "info": 2}
        self.findings.sort(key=lambda x: (order[x["severity"]], x["check"], x.get("file", "")))
        summary = {k: sum(1 for x in self.findings if x["severity"] == k) for k in order}
        truncated = len(self.findings) > self.limit
        result = {"ok": summary["error"] == 0 and not truncated, "complete": not truncated, "truncated": truncated,
                  "evidence_level": "static", "limits": LIMITS, "fingerprint": self.fingerprint(),
                  "summary": summary, "inventory": self.inv, "findings": self.findings[:self.limit]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("静态审计完成：error %(error)d，warn %(warn)d，info %(info)d" % summary
              + ("；输出被截断，结果不完整，不能作为通过依据（用 --max-findings 调大）" if truncated else "")
              + "。error 0 不代表文档正确，见 limits。", file=sys.stderr)
        sys.exit(0 if result["ok"] else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--base")
    ap.add_argument("--rename", action="append", default=[], metavar="OLD=NEW")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    ap.add_argument("--max-findings", type=int, default=200)
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if not os.path.isdir(root):
        print("错误: --root 不是目录: %s" % root, file=sys.stderr)
        sys.exit(2)
    code, top = sh(["git", "rev-parse", "--show-toplevel"], root)
    if code == 0 and top.strip():
        root = top.decode().strip()
    renames = []
    for r in a.rename:
        if "=" not in r or not r.split("=", 1)[0]:
            print("错误: --rename 格式应为 OLD=NEW，收到: %s" % r, file=sys.stderr)
            sys.exit(2)
        renames.append(tuple(r.split("=", 1)))
    if a.max_findings < 1:
        print("错误: --max-findings 必须大于 0", file=sys.stderr)
        sys.exit(2)
    Audit(root, a.base, renames, a.exclude, a.max_findings).run()


if __name__ == "__main__":
    main()
