#!/usr/bin/env python3
"""de.py — deciding-and-executing 的工作区、闸门与归档脚本（仅用标准库，Python 3.8+）。

设计原则：脚本只宣称它能验证的东西。能验证的就强制（结构、状态转换、命令退出码、
路径边界、内容是否变化）；不能验证的（是不是真人批准）只做防误操作，并在输出里说明。

用法（在项目任意目录运行；工作区默认位于 git 仓库根目录的 .decision/）:
  de.py init     [--name 名称] [--risk standard|high] [--lang zh|en]
  de.py list                              # 列出本仓库所有工作区
  de.py check    card|plan
  de.py gate     A|B|AB [--confirm TOKEN]       # 闸门 A=决策卡，B=计划，AB=标准档一次确认两者；两步确认
  de.py status
  de.py preflight                         # 只读：环境/Git/验证命令检查
  de.py coverage                          # 只读：成功标准与证据对应关系
  de.py step     ID --status STATUS [--evidence 文本 | --artifact 路径] [--hours H] [--note 文本] [--confirm TOKEN]
  de.py verify   ID | --all [--timeout 秒]      # 由脚本执行验证命令（verify_argv 或 verify_cmd）并记录退出码
  de.py fail     ID --note 文本 [--hours H]
  de.py replan   ID --note 文本 [--waive 理由 [--confirm TOKEN]]
  de.py reopen   ID --reason 文本
  de.py review   --verdict pass|fix|fail [--blocker 文本 ...] [--confirm TOKEN]
  de.py archive  [--outcome 完成|止损|放弃] [--docs-dir docs/decisions] [--apply]
  de.py sync     --report 文件 [--audit-json 工作区/closeout-audit.json]
  de.py closeout --report 文件 [--outcome …] [--apply]   # archive + sync 一步完成（先预览）
  de.py purge    [--confirm TOKEN]
  de.py show
  公共参数: --dir 工作区目录（必须位于项目内；也可用环境变量 DE_WORKSPACE）

文件归属: plan.json 是 Agent 编写的计划结构；state.json（状态、证据、闸门、审查）只由本脚本写入，
  每次写入的摘要记在 events.jsonl，status 会发现在脚本之外对它的修改。

步骤状态: todo | in_progress | implemented | done | blocked | needs_replan
  合法转换: todo→in_progress|blocked；in_progress→implemented|done|blocked|todo；
            implemented→done|in_progress；blocked→todo|in_progress；
            done→（只能 reopen）；needs_replan→（只能 replan）

两步确认（gate、review、replan --waive、不可逆步骤、purge）:
  第一次调用不带 --confirm：只展示要确认的内容并返回 token，退出码 3。
  第二次带 --confirm TOKEN：内容未变才执行。token 由内容计算，内容一变就失效。
  token 只能防止"一步到位的误操作"和"确认过期内容"，不能证明是真人确认；
  真正的人工授权请用宿主的审批规则，见 references/permissions.md。

输出: JSON 写到 stdout（show 输出 Markdown），提示写到 stderr。
退出码: 0 成功；1 检查未通过；2 用法错误/文件缺失/数据格式错误；3 闸门拒绝或需要确认。
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL_DIR, "assets")


def skill_version():
    """版本号的唯一来源是 SKILL.md 的 metadata.version。"""
    try:
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            m = re.search(r'^\s*version:\s*"?([\w.-]+)"?', f.read(), re.M)
        return m.group(1) if m else "unknown"
    except OSError:
        return "unknown"


VERSION = skill_version()
MARKER = ".de-workspace"
REVIEW_REPORT = "independent-review.md"
WORKSPACE_FILES = {MARKER, "decision-card.md", "plan.json", "state.json", "events.jsonl", "progress.md",
                   "retro.md", "ARCHIVED", "closeout-audit.json", "closeout-report.md", REVIEW_REPORT}
STATUSES = ["todo", "in_progress", "implemented", "done", "blocked", "needs_replan"]
STATUS_ZH = {"todo": "待做", "in_progress": "进行中", "implemented": "已实现未验证", "done": "完成",
             "blocked": "阻塞", "needs_replan": "待重新规划"}
TRANSITIONS = {"todo": {"in_progress", "blocked"},
               "in_progress": {"implemented", "done", "blocked", "todo"},
               "implemented": {"done", "in_progress"},
               "blocked": {"todo", "in_progress"},
               "done": set(), "needs_replan": set()}
STATUS_EN = {"todo": "todo", "in_progress": "in progress", "implemented": "implemented, unverified",
             "done": "done", "blocked": "blocked", "needs_replan": "needs replan"}
RISKS = ["standard", "high"]
LANGS = ["zh", "en"]
OUTCOMES = ["完成", "止损", "放弃"]
OUTCOME_ALIASES = {"done": "完成", "stopped": "止损", "abandoned": "放弃"}
VERDICT_EN = (("go with changes", "改后做"), ("go", "做"), ("drop", "放弃"))
# 章节与字段的英文别名：英文决策卡 / 复盘按同一套规则解析，内部统一用中文名
SECTION_ALIASES = {"目标": ("goal",), "成功标准": ("success criteria",), "非目标": ("non-goals", "non goals"),
                   "关键假设": ("key assumptions", "assumptions"), "止损条件": ("stop-loss", "stop loss"),
                   "升级阈值": ("escalation",), "最大风险": ("biggest risk",), "修订记录": ("revision history",),
                   "原本预期": ("expected",), "实际发生": ("what happened",), "差异的原因": ("why it differed",)}
FIELD_ALIASES = {"结论": ("verdict",), "置信度及依据": ("confidence",), "期限": ("deadline",),
                 "触发状态": ("trigger",), "动作": ("action",), "日期": ("date",)}
_SECTION_LOOKUP = {alias: zh for zh, aliases in SECTION_ALIASES.items() for alias in aliases}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             "vendor", "target", ".tox", ".mypy_cache", ".pytest_cache", "coverage"}   # 与 audit.py 一致
CARD_SECTIONS = ["目标", "成功标准", "非目标", "关键假设", "止损条件"]
GATE_A_SECTIONS = CARD_SECTIONS.copy()   # 改动这些即"方向变了"，闸门 A 失效
STRUCT_FIELDS = ["id", "title", "done_when", "verify", "verify_cmd", "depends_on", "tests_assumption",
                 "covers", "irreversible", "estimate_h"]          # 改动这些即"计划变了"，闸门 B 失效
VAGUE_WORDS = ["更好", "优秀", "满意", "提升", "改善", "尽量", "体验好", "高质量", "顺利",
               "better", "great", "improve", "smooth", "high quality", "user-friendly"]
RETRO_SECTIONS = ["原本预期", "实际发生", "差异的原因"]
DEFAULT_MAX_FAILS = 2       # 第三次盲试的成功率通常不高于前两次，此时更可能是计划或假设有问题
OUTPUT_TAIL = 2000          # 命令输出只保留末尾，防止计划文件膨胀


# ---------------------------------------------------------------- 基础
class Refuse(Exception):
    def __init__(self, reason, code=3, **extra):
        super().__init__(reason)
        self.reason, self.code, self.extra = reason, code, extra


_CTX = None     # main() 构造好的上下文；out() 用它给缺少 next 的输出补一个兜底的下一步


def out(obj, code=0):
    if isinstance(obj, dict) and "next" not in obj:
        obj = dict(obj, next=fallback_next(_CTX))
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def fallback_next(ctx):
    """不重新计算快照的兜底下一步：先看状态。"""
    if ctx is None:
        return {"cmd": None, "why": T(None, "next.fix_dir")}
    if not os.path.isfile(ctx.p(MARKER)):
        return nx(ctx, ("init",), "next.init")
    return nx(ctx, ("status",), "next.status")


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha(obj, n=64):
    data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:n]


def token_for(kind, payload):
    return sha({"kind": kind, "payload": payload}, 10)


def run(args, cwd, timeout=60):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, b""


def project_root(start):
    code, o = run(["git", "rev-parse", "--show-toplevel"], start)
    if code == 0 and o.strip():
        return os.path.realpath(o.decode("utf-8", "replace").strip()), True
    return os.path.realpath(start), False


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


class Ctx:
    """解析项目根目录与工作区位置，并做边界检查。"""

    def __init__(self, dir_arg):
        self.root, self.git = project_root(os.getcwd())
        dir_arg = dir_arg or os.environ.get("DE_WORKSPACE")
        raw = dir_arg if dir_arg else os.path.join(self.root, ".decision")
        raw = raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)
        self.dir_raw = os.path.normpath(raw)
        if os.path.islink(self.dir_raw):
            raise Refuse("工作区 %s 是符号链接，拒绝使用" % self.dir_raw, 2)
        self.dir = os.path.realpath(self.dir_raw)
        if not inside(self.dir, self.root) or self.dir == self.root:
            raise Refuse("工作区必须是项目根目录 %s 之下的子目录，收到 %s" % (self.root, self.dir), 2)
        self.rel = os.path.relpath(self.dir, self.root)
        self._lang = None

    def p(self, name):
        return os.path.join(self.dir, name)

    def require(self):
        if not os.path.isfile(self.p(MARKER)):
            raise Refuse("%s 不是由 de.py init 创建的工作区（缺少 %s）" % (self.dir, MARKER), 2)

    def lang(self):
        if self._lang:
            return self._lang
        try:
            with open(self.p(MARKER), encoding="utf-8") as f:
                lang = json.load(f).get("lang", "zh")
        except (OSError, ValueError, AttributeError):
            return "zh"             # 标记还不存在或损坏时不缓存，init 之后能读到真实语言
        self._lang = lang if lang in LANGS else "zh"
        return self._lang

    def default_dir(self):
        return self.dir == os.path.realpath(os.path.join(self.root, ".decision"))


# ---------------------------------------------------------------- 下一步命令的拼装
_SAFE_ARG = re.compile(r"^[\w./:@%+=,-]+$")


def _quote(x):
    x = str(x)
    return x if _SAFE_ARG.match(x) else '"%s"' % x.replace('"', '\\"')


def dir_arg(ctx):
    """非默认工作区需要在命令里带 --dir；路径相对当前目录（Ctx 就是这样解析 --dir 的）。"""
    if ctx is None or ctx.default_dir():
        return None
    try:
        rel = os.path.relpath(ctx.dir, os.getcwd())
    except ValueError:          # Windows 上跨盘符
        rel = ctx.dir
    return rel.replace(os.sep, "/")


def de_cmd(ctx, *parts):
    """拼出一条可以直接运行的 de.py 命令（文档里 de.py 是脚本完整路径的简写）。"""
    args = [str(p) for p in parts if p is not None]
    d = dir_arg(ctx)
    if d:
        args += ["--dir", d]
    return "de.py " + " ".join(_quote(x) for x in args)


def invocation_parts(drop=("--confirm",)):
    """本次调用的参数，去掉 --dir（de_cmd 会重新加）和 drop 里的选项。"""
    parts, args, i = [], sys.argv[1:], 0
    skip = set(drop) | {"--dir"}
    while i < len(args):
        x = args[i]
        if x in skip:
            i += 2
            continue
        if any(x.startswith(k + "=") for k in skip):
            i += 1
            continue
        parts.append(x)
        i += 1
    return parts


_WORKSPACES = {}


def find_workspaces(root, git):
    """本仓库里所有带标记的工作区（相对路径）。跳过规则与 audit.py 相同，保证两边指纹一致。
    一次命令里结果不变，缓存起来，避免每次算指纹都多跑一次 git。"""
    key = (root, git)
    if key not in _WORKSPACES:
        _WORKSPACES[key] = _scan_workspaces(root, git)
    return _WORKSPACES[key]


def _scan_workspaces(root, git):
    found = set()
    if git:
        code, o = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                       ":(glob)**/" + MARKER], root)
        for n in (o.split(b"\0") if code == 0 else []):
            d = os.path.dirname(os.fsdecode(n)).replace(os.sep, "/") if n else ""
            if d and not set(d.split("/")) & SKIP_DIRS and os.path.isfile(os.path.join(root, d, MARKER)):
                found.add(d)
    if os.path.isfile(os.path.join(root, ".decision", MARKER)):
        found.add(".decision")
    return sorted(found)


# ---------------------------------------------------------------- 指纹：代码当前状态
MAX_UNTRACKED_BYTES = 32 * 1024 * 1024  # 单文件上限
MAX_UNTRACKED_TOTAL_BYTES = 128 * 1024 * 1024  # 总量上限，超限拒绝验证


def fingerprint(ctx):
    """HEAD、工作区外的 Git 状态/差异和未跟踪文件内容。忽略文件不在覆盖范围。"""
    if not ctx.git:
        return None
    code, head = run(["git", "rev-parse", "HEAD"], ctx.root)
    head = head.decode().strip() if code == 0 else "NO_COMMIT"
    spaces = set(find_workspaces(ctx.root, True)) | {ctx.rel.replace(os.sep, "/")}
    excl = [":(exclude)%s" % w for w in sorted(spaces)]
    commands = [
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."] + excl,
        ["git", "diff", "HEAD", "--binary", "--", "."] + excl,
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "."] + excl,
    ]
    results = [run(c, ctx.root) for c in commands]
    if any(code != 0 for code, _ in results):
        raise Refuse("Git 状态或差异读取失败，无法证明证据仍对应当前代码", 2)
    st, diff, untracked = (v for _, v in results)
    h = hashlib.sha256()
    h.update(st)
    h.update(diff)
    total_bytes = 0
    for name in sorted(n for n in untracked.split(b"\0") if n):
        rel = os.fsdecode(name)
        path = os.path.join(ctx.root, rel)
        h.update(b"\0path\0" + name + b"\0")
        if os.path.islink(path):
            h.update(b"symlink\0" + os.fsencode(os.readlink(path)))
        else:
            try:
                size = os.path.getsize(path)
                total_bytes += size
                if size > MAX_UNTRACKED_BYTES or total_bytes > MAX_UNTRACKED_TOTAL_BYTES:
                    raise Refuse("未跟踪文件过大（单文件 32 MiB / 总量 128 MiB 上限），应提交、忽略或缩小验证范围：%s" % rel, 3)
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
            except OSError as e:
                raise Refuse("无法读取未跟踪文件 %s：%s；不能生成可信指纹" % (rel, e), 3)
    return head[:12] + ("" if not st else "+" + h.hexdigest()[:12])


# ---------------------------------------------------------------- 事件与读写
# plan.json 归 Agent（计划结构）；state.json 归脚本（状态、证据、闸门、审查）。Agent 照常编辑 plan.json
# 动不到运行时状态；plan.json 里出现的运行时字段一律忽略，并在 status 中提示。
RUNTIME_STEP_KEYS = ("status", "fails", "spent_h", "evidence", "evidence_history", "started_at", "finished_at",
                     "escalation", "escalation_history", "waivers", "last_verify", "fail_mark")
RUNTIME_TOP_KEYS = ("gates", "review", "last_event")


def step_defaults():
    return {"status": "todo", "fails": 0, "spent_h": 0, "evidence": []}


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        raise Refuse("%s 不是合法 JSON：%s" % (what, e), 2)


def state_of(plan):
    st = {"schema": 1, "steps": {}}
    for k in RUNTIME_TOP_KEYS:
        if plan.get(k) is not None:
            st[k] = plan[k]
    for step in plan.get("steps", []):
        if isinstance(step, dict):
            st["steps"][sid_key(step.get("id"))] = {k: step[k] for k in RUNTIME_STEP_KEYS if k in step}
    return st


def load_plan(ctx):
    """读取 plan.json（结构）并合并 state.json（运行时状态），返回与旧版相同形状的计划对象。"""
    path = ctx.p("plan.json")
    if not os.path.exists(path):
        raise Refuse("找不到 %s，先运行 init" % path, 2)
    plan = read_json(path, "plan.json")
    errs = schema_errors(plan)
    if errs:
        raise Refuse("plan.json 结构错误：" + "；".join(errs), 2, errors=errs)
    legacy = not os.path.exists(ctx.p("state.json"))
    if legacy:      # 4.2 之前的工作区：运行时状态还在 plan.json 里，下一次写入时迁移
        state = state_of(plan)
    else:
        state = read_json(ctx.p("state.json"), "state.json")
        if not isinstance(state, dict) or not isinstance(state.get("steps", {}), dict):
            raise Refuse("state.json 结构错误：顶层与 steps 都必须是对象", 2)
    had_runtime, ignored = False, []
    for step in plan["steps"]:
        sid = sid_key(step.get("id"))
        rt = state.get("steps", {}).get(sid) or {}
        expected = dict(step_defaults(), **(rt if isinstance(rt, dict) else {}))
        for k in RUNTIME_STEP_KEYS:
            if k in step:
                had_runtime = True
                if not legacy and step[k] != expected.get(k):
                    ignored.append("步骤 %s 的 %s" % (sid, k))
                del step[k]
        step.update(expected)
    defaults = {"gates": {}, "last_event": 0, "review": None}
    for k in RUNTIME_TOP_KEYS:
        if k in plan:
            had_runtime = True
            if not legacy and plan[k] != state.get(k, defaults[k]):
                ignored.append(k)
            del plan[k]
        if state.get(k) is not None:
            plan[k] = state[k]
    plan.setdefault("gates", {})
    plan.setdefault("last_event", 0)
    errs = schema_errors(plan)
    if errs:
        raise Refuse("state.json 内容不合法：" + "；".join(errs), 2, errors=errs)
    plan["_meta"] = {"legacy": legacy, "had_runtime": had_runtime, "ignored": ignored}
    return plan


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_plan(ctx, plan, state=None):
    write_atomic(ctx.p("state.json"), state if state is not None else state_of(plan))
    meta = plan.get("_meta") or {}
    if meta.get("legacy") and meta.get("had_runtime"):     # 迁移：把运行时字段从 plan.json 中移走
        structure = {k: v for k, v in plan.items() if k not in RUNTIME_TOP_KEYS and not k.startswith("_")}
        structure["steps"] = [{k: v for k, v in st.items() if k not in RUNTIME_STEP_KEYS} for st in plan["steps"]]
        write_atomic(ctx.p("plan.json"), structure)
    plan["_meta"] = dict(meta, legacy=False, had_runtime=False)


def read_events(ctx):
    path, events = ctx.p("events.jsonl"), []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    events.append(ev)
    return events


def last_event_seq(ctx):
    seq = 0
    for ev in read_events(ctx):
        try:
            seq = max(seq, int(ev.get("seq", 0)))
        except (TypeError, ValueError):
            pass
    return seq


def commit(ctx, plan, etype, human, **data):
    """先追加事件（含即将写入的 state.json 摘要），再原子替换 state.json；中断或手改时 status 能发现。"""
    seq = last_event_seq(ctx) + 1
    state = None
    if plan is not None:
        plan["last_event"] = seq
        state = state_of(plan)
        data["state_sha"] = sha(state, 16)
    ev = dict(seq=seq, at=now(), type=etype, **data)
    with open(ctx.p("events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    if plan is not None:
        save_plan(ctx, plan, state)
    with open(ctx.p("progress.md"), "a", encoding="utf-8") as f:
        f.write("\n- %s %s\n" % (ev["at"], human))
    return seq


def state_warnings(ctx, plan, events=None):
    """state.json 是否由 de.py 最后一次写入；plan.json 里是否混入了会被忽略的运行时字段。"""
    w, meta = [], plan.get("_meta") or {}
    if meta.get("legacy"):
        w.append("工作区来自 4.2 之前的版本：运行时状态仍在 plan.json，下一次写入命令会自动迁移到 state.json")
    if meta.get("ignored"):
        w.append("plan.json 里的运行时字段由脚本维护（实际值在 state.json），以下内容与实际状态不同，已忽略：%s"
                 % "、".join(meta["ignored"][:10]))
    if os.path.exists(ctx.p("state.json")):
        st = read_json(ctx.p("state.json"), "state.json")
        events = read_events(ctx) if events is None else events
        ev = next((e for e in events if e.get("seq") == st.get("last_event")), {})
        if ev.get("state_sha") and ev["state_sha"] != sha(st, 16):
            w.append("state.json 与事件日志记录的摘要不一致：它在 de.py 之外被修改过，状态与证据不可信，请对照 events.jsonl 检查")
    return w


# ---------------------------------------------------------------- 结构校验
def schema_errors(plan):
    e = []
    if not isinstance(plan, dict):
        return ["顶层必须是对象"]
    if plan.get("risk", "standard") not in RISKS:
        e.append("risk 必须是 %s 之一" % "/".join(RISKS))
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return e + ["steps 必须是数组"]
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            e.append("第 %d 个步骤不是对象" % i)
            continue
        sid = s.get("id")
        if isinstance(sid, bool) or not isinstance(sid, (int, str)) or (isinstance(sid, str) and not sid.strip()):
            e.append("第 %d 个步骤的 id 必须是非空字符串或整数，收到 %r" % (i, sid))
        if s.get("status", "todo") not in STATUSES:
            e.append("步骤 %r 的状态 %r 不合法" % (sid, s.get("status")))
        for k in ("title", "done_when", "verify", "verify_cmd", "tests_assumption"):
            if k in s and s[k] is not None and not isinstance(s[k], str):
                e.append("步骤 %r 的 %s 必须是字符串" % (sid, k))
        argv = s.get("verify_argv")
        if argv is not None and (not isinstance(argv, list)
                                 or not all(isinstance(x, str) and x for x in argv)):
            e.append("步骤 %r 的 verify_argv 必须是非空字符串组成的数组" % (sid,))
        for k in ("depends_on", "covers", "evidence", "evidence_history"):
            if k in s and not isinstance(s[k], list):
                e.append("步骤 %r 的 %s 必须是数组" % (sid, k))
        for k in ("estimate_h", "spent_h", "fails"):
            if k in s and (isinstance(s[k], bool) or not isinstance(s[k], (int, float))):
                e.append("步骤 %r 的 %s 必须是数字" % (sid, k))
        if "irreversible" in s and not isinstance(s["irreversible"], bool):
            e.append("步骤 %r 的 irreversible 必须是 true/false" % sid)
    return e


def sid_key(x):
    return str(x)


def find_step(plan, sid):
    for s in plan["steps"]:
        if sid_key(s.get("id")) == sid_key(sid):
            return s
    raise Refuse("步骤 %s 不存在。可用 id: %s" % (sid, ", ".join(sid_key(s.get("id")) for s in plan["steps"])), 2)


def struct_of(step):
    d = {k: step.get(k) for k in STRUCT_FIELDS}
    if "verify_argv" in step:       # 只在出现时纳入，旧计划的批准哈希保持不变
        d["verify_argv"] = step.get("verify_argv")
    return d


def plan_hash(plan):
    return sha({"risk": plan.get("risk", "standard"), "name": plan.get("name"),
                "first_step": plan.get("first_step"), "if_then": plan.get("if_then"),
                "steps": [struct_of(s) for s in plan["steps"]]}, 16)


# ---------------------------------------------------------------- 决策卡
def canonical_section(title):
    t = re.sub(r"[（(].*$", "", title).strip()
    return _SECTION_LOOKUP.get(t.lower(), t)


def read_card(ctx):
    path = ctx.p("decision-card.md")
    if not os.path.exists(path):
        raise Refuse("找不到决策卡 %s" % path, 2)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sec, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = canonical_section(m.group(1))
            sec[cur] = []
        elif cur is not None:
            sec[cur].append(line)
    return text, sec


_PLACEHOLDERS = None


def placeholders():
    """模板里原样出现的方括号占位符（如「[名称]」）。只有它们算"没填"；用户写的 [400]、[P1] 是正常内容。"""
    global _PLACEHOLDERS
    if _PLACEHOLDERS is None:
        found = {"[名称]", "[YYYY-MM-DD]"}

        def strings(x):
            if isinstance(x, str):
                yield x
            elif isinstance(x, list):
                for v in x:
                    yield from strings(v)
            elif isinstance(x, dict):
                for v in x.values():
                    yield from strings(v)

        for base, _, names in os.walk(ASSETS):
            for name in names:
                try:
                    with open(os.path.join(base, name), encoding="utf-8") as f:
                        text = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if name.endswith(".json"):
                    try:
                        text = "\n".join(strings(json.loads(text)))
                    except ValueError:
                        continue
                found |= set(re.findall(r"\[[^\[\]\n]+\](?!\()", text))
        _PLACEHOLDERS = found
    return _PLACEHOLDERS


def is_placeholder(text):
    return any(p in text for p in placeholders())


def meaningful(lines):
    keep = []
    for l in lines:
        s = l.strip()
        if not s or re.fullmatch(r"[-*|:\s]+", s) or re.fullmatch(r"(\d+[.、]|[-*])\s*", s):
            continue
        if is_placeholder(s) or s.startswith("| #") or s.startswith("|---"):
            continue
        keep.append(s)
    return keep


def field(lines, name):
    names = "|".join(re.escape(n) for n in (name,) + FIELD_ALIASES.get(name, ()))
    for l in lines:
        m = re.match(r"^\s*[-*]?\s*(?:%s)[:：]\s*(.*?)\s*$" % names, l, re.I)
        if m and m.group(1) and not is_placeholder(m.group(1)):
            return m.group(1)
    return None


def card_info(ctx):
    text, sec = read_card(ctx)
    head = text.split("\n## ", 1)[0].splitlines()
    verdict_raw = field(head, "结论")
    verdict = None
    if verdict_raw:
        m = re.match(r"^(改后做|放弃|做)(?=$|[\s（(：:,，—-])", verdict_raw)
        verdict = m.group(1) if m else None
        for en, zh in VERDICT_EN if verdict is None else ():
            if re.match(r"^%s(?=$|[\s(:,—-])" % re.escape(en), verdict_raw.lower()):
                verdict = zh
                break
    kill = sec.get("止损条件", [])
    deadline_raw = field(kill, "期限")
    deadline = None
    if deadline_raw:
        try:
            deadline = dt.date.fromisoformat(deadline_raw[:10])
        except ValueError:
            deadline = "invalid"
    criteria = [l for l in meaningful(sec.get("成功标准", [])) if re.match(r"^\d+[.、]", l)]
    mf = re.search(r"(?:修复失败次数上限|max fails)[:：]\s*(\d+)", text, re.I)
    return {"text": text, "sec": sec, "verdict_raw": verdict_raw, "verdict": verdict, "deadline": deadline,
            "trigger": field(kill, "触发状态"), "action": field(kill, "动作"), "criteria": criteria,
            "max_fails": max(1, int(mf.group(1))) if mf else DEFAULT_MAX_FAILS,
            "assumptions": [l for l in meaningful(sec.get("关键假设", [])) if re.search(r"\|\s*A\d+\s*\|", l)]}


def card_errors(ci):
    errors, warnings = [], []
    for s in CARD_SECTIONS:
        if s not in ci["sec"]:
            errors.append("缺少章节「%s」" % s)
        elif not meaningful(ci["sec"][s]):
            errors.append("章节「%s」是空的或只有占位符" % s)
    if ci["verdict"] is None:
        errors.append("「结论：」必须以 做 / 改后做 / 放弃 之一开头（英文卡片：go / go with changes / drop），收到：%r"
                      % ci["verdict_raw"])
    if not ci["criteria"]:
        errors.append("成功标准需要编号条目（1. 2. …），计划用编号建立覆盖关系")
    for c in ci["criteria"]:
        body = re.sub(r"^\d+[.、]\s*", "", c)
        if any(w in body.lower() for w in VAGUE_WORDS) and not re.search(r"\d", body):
            warnings.append("成功标准可能无法验证（含模糊词且没有数字）：「%s」" % c)
    if "关键假设" in ci["sec"] and not ci["assumptions"]:
        errors.append("关键假设表里没有编号为 A1、A2… 的假设")
    if ci["deadline"] in (None, "invalid"):
        errors.append("止损条件缺少「- 期限：YYYY-MM-DD」或日期格式不对")
    if not ci["trigger"]:
        errors.append("止损条件缺少「- 触发状态：……」（可观察的状态）")
    if not ci["action"]:
        errors.append("止损条件缺少「- 动作：……」（触发后做什么）")
    conf = field(ci["text"].split("\n## ", 1)[0].splitlines(), "置信度及依据")
    if not conf:
        warnings.append("置信度为空，或只写了数字没有依据")
    elif not re.search(r"[，,。；;：:]|依据|because|based on", conf, re.I):
        warnings.append("置信度似乎没有写依据：%s" % conf)
    return errors, warnings


def gate_a_hash(ci):
    """关键假设的内容需要审批；只有进展状态列允许随验证更新而不重新审批。"""
    approved = {}
    for name in GATE_A_SECTIONS:
        lines = []
        for line in ci["sec"].get(name, []):
            line = line.strip()
            if not line:
                continue
            if name == "关键假设" and line.startswith("|") and line.endswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                # 决策卡中假设表的第四列为动态「状态」。第一至三列仍进入审批哈希。
                if len(cells) == 4:
                    line = "|" + "|".join(cells[:3]) + "|"
            lines.append(line)
        approved[name] = lines
    payload = {"verdict": ci["verdict"], "sec": approved}
    # 失败次数上限决定何时强制升级，放宽它等于改了止损规则，也需要审批。
    # 取默认值时不入哈希，使沿用默认上限的已有工作区升级后闸门仍然有效。
    if ci["max_fails"] != DEFAULT_MAX_FAILS:
        payload["max_fails"] = ci["max_fails"]
    return sha(payload, 16)


# ---------------------------------------------------------------- 计划校验
def plan_errors(plan, ci):
    errors, warnings = [], []
    steps, risk = plan["steps"], plan.get("risk", "standard")
    if not steps:
        errors.append("steps 为空：至少需要一个步骤")
    ids = [sid_key(s.get("id")) for s in steps]
    if len(ids) != len(set(ids)):
        errors.append("步骤 id 有重复")
    idset = set(ids)
    for s in steps:
        sid = sid_key(s.get("id"))
        for k, zh in [("title", "步骤名"), ("done_when", "完成判据"), ("verify", "验证方法")]:
            v = str(s.get(k) or "").strip()
            if not v or is_placeholder(v):
                errors.append("步骤 %s 缺少%s（%s）" % (sid, zh, k))
        for d in s.get("depends_on", []):
            if sid_key(d) not in idset:
                errors.append("步骤 %s 依赖不存在的步骤 %s" % (sid, d))
        if s.get("status") == "done" and not s.get("evidence"):
            errors.append("步骤 %s 标记为 done 但没有证据" % sid)
        est = s.get("estimate_h")
        if isinstance(est, (int, float)) and est > 8:
            warnings.append("步骤 %s 预计 %sh，超过一个工作时段，建议继续拆分" % (sid, est))
        if str(s.get("verify_cmd") or "").strip() and s.get("verify_argv"):
            errors.append("步骤 %s 同时写了 verify_cmd 和 verify_argv，只能保留一种" % sid)
        if risk == "high" and not has_verify(s):
            warnings.append("高风险计划中步骤 %s 没有验证命令（verify_argv / verify_cmd）：只能用文件证据完成" % sid)
    graph = {sid_key(s.get("id")): [sid_key(d) for d in s.get("depends_on", [])] for s in steps}
    seen, stack = set(), set()

    def cyc(n):
        if n in stack:
            return True
        if n in seen:
            return False
        seen.add(n)
        stack.add(n)
        r = any(cyc(m) for m in graph.get(n, []) if m in graph)
        stack.discard(n)
        return r
    if any(cyc(n) for n in list(graph)):
        errors.append("depends_on 存在循环依赖")
    n = len(ci["criteria"])
    covered = set()
    for s in steps:
        for c in s.get("covers", []):
            if isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= n:
                covered.add(c)
            else:
                errors.append("步骤 %s 的 covers 引用了不存在的成功标准 %r（共 %d 条）" % (sid_key(s.get("id")), c, n))
    missing = [i for i in range(1, n + 1) if i not in covered]
    if missing:
        msg = "成功标准 %s 没有任何步骤覆盖（在步骤的 covers 里写编号）" % missing
        (errors if risk == "high" else warnings).append(msg)
    tested = [s for s in steps if str(s.get("tests_assumption") or "").strip()]
    if steps and not tested:
        warnings.append("没有步骤标注 tests_assumption：最危险的假设没有被安排验证")
    elif tested and steps.index(tested[0]) > 1:
        warnings.append("第一个验证假设的步骤排在第 %d 位；通常应放在前两步" % (steps.index(tested[0]) + 1))
    real_if = [x for x in plan.get("if_then", []) if isinstance(x, dict) and str(x.get("if", "")).strip()
               and not is_placeholder(str(x.get("if")))]
    if len(real_if) < 2:
        warnings.append("if_then 预案少于 2 条")
    if steps and sid_key(plan.get("first_step")) not in idset:
        errors.append("first_step 未指向已有步骤")
    return errors, warnings


# ---------------------------------------------------------------- 闸门
def gate_state(plan, ci):
    g = plan.get("gates", {})
    a = g.get("A")
    a_state = "missing" if not a else ("valid" if a.get("hash") == gate_a_hash(ci) else "stale")
    b = g.get("B")
    if not b:
        b_state = "missing"
    elif a_state != "valid" or b.get("a_hash") != (a or {}).get("hash"):
        b_state = "stale"
    else:
        b_state = "valid" if b.get("hash") == plan_hash(plan) else "stale"
    return {"A": a_state, "B": b_state}


def effective_max_fails(plan, ci):
    """未经确认的放宽不生效：闸门 A 失效时，取已确认的上限与卡片当前值中较严的一个。"""
    a = plan.get("gates", {}).get("A") or {}
    if a.get("hash") == gate_a_hash(ci):
        return ci["max_fails"]
    return min(ci["max_fails"], a.get("max_fails", DEFAULT_MAX_FAILS))


def escalate_step(plan, ci, s, source):
    """失败次数到达（已确认的）上限时转为待重新规划。返回 (是否升级, 上限)。"""
    max_fails = effective_max_fails(plan, ci)
    esc = int(s.get("fails", 0)) >= max_fails
    if esc:
        s["escalation"] = {"at": now(), "fails": s["fails"], "struct_hash": sha(struct_of(s), 16),
                           "prev_status": s.get("status", "todo"), "source": source}
        s["status"] = "needs_replan"
    return esc, max_fails


COUNTABLE = ("in_progress", "implemented")


def track_verify(plan, ci, s, ev):
    """脚本亲眼看到的失败自动计数："改了代码仍然失败"才算一次修复失败。
    - 第一次失败是基线（先写测试、先看红灯），不计；同一指纹重复运行不计；
    - 执行期间代码变了的运行既不计数，也不更新基线；非 git（无指纹）不自动计数；
    - 只在 in_progress / implemented 时计数；已被手动 fail 记过的指纹不再重复计；
    - 通过只重置基线，不清零 fails（replan --waive 的"再失败一次就升级"仍然成立）。"""
    res = {"counted": False, "fails": int(s.get("fails", 0)), "escalate": False,
           "max_fails": effective_max_fails(plan, ci)}
    if ev.get("note"):
        return res
    fp, cmd_id = ev.get("fingerprint"), sha(ev.get("cmd") or "", 16)
    prev = s.get("last_verify") if isinstance(s.get("last_verify"), dict) else None
    mark = s.get("fail_mark") if isinstance(s.get("fail_mark"), dict) else {}
    if (not ev["ok"] and fp is not None and s.get("status") in COUNTABLE and prev and prev.get("ok") is False
            and prev.get("cmd") == cmd_id and prev.get("fp") != fp and mark.get("fp") != fp):
        s["fails"] = int(s.get("fails", 0)) + 1
        s["fail_mark"] = {"fp": fp, "by": "auto", "at": now(), "absorbed": False}
        esc, max_fails = escalate_step(plan, ci, s, "auto")
        res.update(counted=True, fails=s["fails"], escalate=esc, max_fails=max_fails)
    s["last_verify"] = {"ok": bool(ev["ok"]), "fp": fp, "cmd": cmd_id, "at": ev.get("at")}
    return res


def count_note(t):
    if t["escalate"]:
        return "已自动计为一次修复失败（%d/%d），达到上限，步骤转为待重新规划" % (t["fails"], t["max_fails"])
    if t["counted"]:
        return "已自动计为一次修复失败（%d/%d）" % (t["fails"], t["max_fails"])
    return "不计入失败次数（第一次失败作为基线，或代码与上次失败时相同；改了代码仍失败才计）"


def require_gate_b(ctx, plan, ci):
    gs = gate_state(plan, ci)
    if gs["B"] != "valid":
        raise Refuse("计划未通过闸门 B，或通过后决策卡/计划结构已改变（A=%s，B=%s）。先运行 gate A / gate B 重新确认"
                     % (gs["A"], gs["B"]), gates=gs, next=gate_next(ctx, plan, gs))


def two_step(ctx, kind, payload, confirm, preview):
    tok = token_for(kind, payload)
    parts = invocation_parts()
    if confirm is None:
        raise Refuse("向用户展示 preview，用户明确同意后带 --confirm %s 重新运行" % tok,
                     3, needs_confirmation=True, token=tok, preview=preview,
                     next=nx(ctx, parts + ["--confirm", tok], "next.confirm", needs_user=True))
    if confirm != tok:
        raise Refuse("确认 token 不匹配：内容已变化或 token 有误。重新运行不带 --confirm 的命令查看最新内容", 3,
                     needs_confirmation=True, next=nx(ctx, parts, "next.confirm_mismatch"))
    return tok


# ---------------------------------------------------------------- 证据
def fresh_command_pass(step, fp):
    ev = [e for e in step.get("evidence", []) if e.get("kind") == "command"]
    return bool(ev) and bool(ev[-1].get("ok")) and fp is not None and ev[-1].get("fingerprint") == fp


def artifact_issues(ctx, step, fp):
    """校验当前 file artifact 仍是原文件、原内容、原指纹；失败返回原因。"""
    evidence = [e for e in step.get("evidence", []) if isinstance(e, dict) and e.get("kind") == "artifact"]
    if not evidence:
        return "没有 artifact 证据"
    ev = evidence[-1]
    rel = ev.get("path")
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        return "artifact 路径无效"
    path = os.path.join(ctx.root, rel)
    if os.path.islink(path) or not inside(path, ctx.root) or not os.path.isfile(path):
        return "artifact 不存在、越界或已成为符号链接"
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest()[:16] != ev.get("sha"):
            return "artifact 内容哈希已变化"
    except OSError as e:
        return "artifact 无法读取：%s" % e
    if fp is not None and ev.get("fingerprint") != fp:
        return "artifact 对应的代码指纹已变化"
    return None


def verify_spec(step):
    """返回 (argv, 显示用命令)。verify_argv 不经 shell 直接执行（跨平台）；verify_cmd 交给系统 shell。"""
    argv = step.get("verify_argv")
    if isinstance(argv, list) and argv:
        return list(argv), shlex.join(argv)
    return None, str(step.get("verify_cmd") or "").strip()


def has_verify(step):
    return bool(verify_spec(step)[1])


def stale_verified_step(ctx, step, fp):
    """只对命令和文件型的可验证证据检查；文字证据维持显式未验证状态。"""
    if has_verify(step):
        return None if fresh_command_pass(step, fp) else "命令验证已失效或未通过"
    if any(isinstance(e, dict) and e.get("kind") == "artifact" for e in step.get("evidence", [])):
        return artifact_issues(ctx, step, fp)
    return None


def run_verify(ctx, step, timeout, fp_before=None):
    argv, cmd = verify_spec(step)
    if not cmd:
        raise Refuse("步骤 %s 没有验证命令（verify_argv / verify_cmd），无法由脚本执行验证" % step.get("id"), 2)
    if fp_before is None:
        fp_before = fingerprint(ctx)
    started = dt.datetime.now()
    try:
        if argv:
            exe = shutil.which(argv[0]) or argv[0]     # Windows 上 npm 等是 .cmd，需按 PATHEXT 解析
            r = subprocess.run([exe] + argv[1:], cwd=ctx.root, capture_output=True, timeout=timeout)
        else:
            r = subprocess.run(cmd, shell=True, cwd=ctx.root, capture_output=True, timeout=timeout)
        code, output = r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired as e:
        code, output = 124, (e.stdout or b"") + (e.stderr or b"") + b"\n[timeout]"
    except OSError as e:
        code, output = 127, ("无法启动验证命令：%s" % e).encode("utf-8")
    text = output.decode("utf-8", "replace")
    fp_after = fingerprint(ctx)
    ev = {"kind": "command", "cmd": cmd, "exit_code": code, "ok": code == 0 and fp_before == fp_after,
          "at": now(), "seconds": round((dt.datetime.now() - started).total_seconds(), 1),
          "fingerprint": fp_after, "output_tail": text[-OUTPUT_TAIL:], "output_sha": sha(output, 16)}
    if fp_before != fp_after:
        ev["note"] = "验证命令执行期间代码发生变化，本次结果不作为通过证据"
    step.setdefault("evidence", []).append(ev)
    return ev


# ---------------------------------------------------------------- 只读预检与验收覆盖
# 这只是已知危险模式提示，绝不是 shell 安全解析器或沙箱。
_VERIFY_HAZARDS = (
    (r"(?i)\b(?:rm|rmdir|del|erase|format|mkfs|shred)\b", "可能删除或破坏文件"),
    (r"(?i)\bgit\s+(?:push|reset|clean|rebase|branch\s+-D)\b", "可能修改 Git 共享或本地状态"),
    (r"(?i)\b(?:curl|wget|Invoke-WebRequest)\b", "可能访问外部网络"),
    (r"(?i)(?:^|[;&|])\s*(?:sudo|powershell|pwsh)\b", "可能获得扩展执行能力"),
    (r"(?:>>?|\|\s*tee\s+)", "可能写入或组合 Shell 操作"),
)


def verify_command_review(cmd):
    """返回需要人工审查的风险信号；无命中不代表命令安全。"""
    return [label for pattern, label in _VERIFY_HAZARDS if re.search(pattern, cmd)]


def cmd_preflight(a, ctx):
    """不会修改工作区。列出环境、Git 状态和即将执行的验证命令。"""
    code, branch = run(["git", "branch", "--show-current"], ctx.root)
    branch = branch.decode("utf-8", "replace").strip() if code == 0 else None
    status_code, raw = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], ctx.root)
    paths = []
    if status_code == 0:
        parts, i = raw.split(b"\0"), 0
        while i < len(parts):
            item, i = parts[i], i + 1
            if len(item) < 4:
                continue
            paths.append(os.fsdecode(item[3:]))
            if b"R" in item[:2] or b"C" in item[:2]:
                i += 1  # 重命名/复制项后面跟着旧路径，不是另一条改动
    checks = []
    warnings = []
    if not ctx.git:
        warnings.append("项目未处于 Git 仓库中：不能依靠代码指纹证明历史证据有效")
    if status_code != 0 and ctx.git:
        warnings.append("无法读取 Git 状态")
    if paths:
        warnings.append("工作区存在改动，执行前应确认它们的归属，不要自动清理")
    if os.path.isfile(ctx.p(MARKER)):
        try:
            plan = load_plan(ctx)
            for step in plan["steps"]:
                cmd = verify_spec(step)[1]
                if not cmd:
                    continue
                checks.append({"step": step["id"], "command": cmd,
                               "review_required": True, "hazards": verify_command_review(cmd)})
        except Refuse as e:
            warnings.append("无法读取当前计划：" + e.reason)
    out({"ok": True, "read_only": True, "root": ctx.root, "git": ctx.git,
         "branch": branch, "dirty_file_count": len(paths), "dirty_paths_preview": paths[:30],
         "workspace_initialized": os.path.isfile(ctx.p(MARKER)),
         "verification_commands": checks, "warnings": warnings,
         "limits": ["未核验依赖安装、设备连接及凭据权限",
                    "命令模式检测只提供提示；所有 shell 命令都可能产生副作用，须在隔离环境并按授权执行",
                    "不修改或清理用户工作树"]})


def coverage_quality(ctx, step, fp, cache):
    """一个步骤作为成功标准证据的质量；同一步骤覆盖多条标准时只算一次（文件证据要重新哈希）。"""
    sid = sid_key(step.get("id"))
    if sid not in cache:
        state = step.get("status", "todo")
        evidence = step.get("evidence", [])
        failure = stale_verified_step(ctx, step, fp) if state == "done" else None
        if state != "done":
            quality = "PENDING"
        elif failure:
            quality = "STALE"
        elif has_verify(step) and fresh_command_pass(step, fp):
            quality = "COMMAND_PASS"
        elif any(isinstance(e, dict) and e.get("kind") == "artifact" for e in evidence):
            quality = "ARTIFACT_INTACT"
        else:
            quality = "UNVERIFIED_NOTE"
        cache[sid] = (quality, failure)
    return cache[sid]


def coverage_rows(ctx, plan, ci, fp, cache=None):
    """只给证据覆盖候选，不把步骤自报 covers 当成成功标准已验证。"""
    cache = {} if cache is None else cache
    items = []
    for line in ci["criteria"]:
        m = re.match(r"^(\d+)[.、]\s*(.*)$", line)
        if not m:
            continue
        cid = int(m.group(1))
        linked = []
        for step in plan["steps"]:
            if cid not in step.get("covers", []):
                continue
            quality, failure = coverage_quality(ctx, step, fp, cache)
            linked.append({"step": step.get("id"), "state": step.get("status", "todo"),
                           "evidence_quality": quality, "reason": failure})
        if not linked:
            status = "NO_COVERAGE"
        elif any(e["evidence_quality"] == "STALE" for e in linked):
            status = "STALE"
        elif any(e["evidence_quality"] in ("PENDING", "UNVERIFIED_NOTE") for e in linked):
            status = "NEEDS_VERIFICATION"
        else:
            status = "READY_FOR_INDEPENDENT_REVIEW"
        items.append({"criterion": cid, "text": m.group(2), "status": status, "steps": linked})
    return items


def cmd_coverage(a, ctx):
    ctx.require()
    snap = collect_status(ctx, full=False, fp=fingerprint(ctx))
    items = coverage_rows(ctx, snap["plan"], snap["ci"], snap["fp"])
    out({"ok": True, "read_only": True, "fingerprint": snap["fp"], "criteria": items,
         "all_ready_for_review": bool(items) and all(x["status"] == "READY_FOR_INDEPENDENT_REVIEW" for x in items),
         "limits": ["covers 由 Agent 编写，不证明测试与真实需求存在语义对应",
                    "命令 PASS 仅证明该命令成功退出；artifact 完整不证明内容属实",
                    "即便全部 READY_FOR_INDEPENDENT_REVIEW，也不等于用户验收通过"],
         "next": snap_next(ctx, snap)})


# ---------------------------------------------------------------- 命令实现
def cmd_init(a, ctx):
    if os.path.exists(ctx.p(MARKER)):
        out({"ok": True, "dir": ctx.dir, "created": [], "note": "工作区已存在，未覆盖任何文件"})
    if os.path.exists(ctx.dir) and os.listdir(ctx.dir):
        raise Refuse("%s 已存在且非空，但不是 de.py 工作区；为避免覆盖，拒绝初始化" % ctx.dir, 2)
    os.makedirs(ctx.dir, exist_ok=True)
    created = []
    tpl = ASSETS if a.lang == "zh" else os.path.join(ASSETS, a.lang)
    for name in ["decision-card.md", "plan.json", "progress.md", "retro.md"]:
        src = os.path.join(tpl, name)
        if not os.path.exists(src):
            raise Refuse("找不到模板 %s，技能目录可能不完整" % src, 2)
        with open(src, encoding="utf-8") as f:
            txt = f.read()
        if a.name:
            txt = txt.replace("[名称]", a.name).replace("[name]", a.name)
        if name == "plan.json":
            d = json.loads(txt)
            d["risk"] = a.risk
            txt = json.dumps(d, ensure_ascii=False, indent=2)
        with open(ctx.p(name), "w", encoding="utf-8") as f:
            f.write(txt)
        created.append(os.path.join(ctx.rel, name))
    with open(ctx.p(MARKER), "w", encoding="utf-8") as f:
        json.dump({"tool": "deciding-and-executing", "version": VERSION, "created": now(), "risk": a.risk,
                   "lang": a.lang}, f)
    commit(ctx, load_plan(ctx), "init", "初始化工作区（风险档位：%s）" % a.risk, risk=a.risk)
    created.append(os.path.join(ctx.rel, "state.json"))
    out({"ok": True, "dir": ctx.dir, "risk": a.risk, "created": created,
         "next": nx(ctx, ("check", "card"), "next.fill_card")})


def cmd_check(a, ctx):
    ctx.require()
    ci = card_info(ctx)
    if a.target == "card":
        errors, warnings = card_errors(ci)
        out({"ok": not errors, "errors": errors, "warnings": warnings,
             "verdict": ci["verdict"], "assumptions": ci["assumptions"],
             "next": nx(ctx, ("check", "card"), "next.fix_card", n=len(errors)) if errors
             else light_next(ctx, ci=ci)}, 0 if not errors else 1)
    plan = load_plan(ctx)
    errors, warnings = plan_errors(plan, ci)
    out({"ok": not errors, "errors": errors, "warnings": warnings, "step_count": len(plan["steps"]),
         "risk": plan.get("risk", "standard"),
         "next": nx(ctx, ("check", "plan"), "next.fix_plan", n=len(errors)) if errors
         else light_next(ctx, plan=plan, ci=ci)}, 0 if not errors else 1)


def gate_a_preview(ci, warnings):
    return {"结论": ci["verdict_raw"], "成功标准": ci["criteria"],
            "止损": {"触发状态": ci["trigger"], "期限": str(ci["deadline"]), "动作": ci["action"]},
            "修复失败次数上限": ci["max_fails"], "warnings": warnings}


def gate_b_preview(plan, warnings):
    return {"risk": plan.get("risk"), "first_step": plan.get("first_step"),
            "steps": [{"id": s.get("id"), "title": s.get("title"), "verify_command": verify_spec(s)[1],
                       "runs_via_shell": bool(verify_spec(s)[1]) and not verify_spec(s)[0],
                       "irreversible": s.get("irreversible", False),
                       "verify_command_review_required": has_verify(s),
                       "verify_command_risk_hints": verify_command_review(verify_spec(s)[1])}
                      for s in plan["steps"]],
            "说明": "确认计划即同意脚本在验证时执行上面列出的验证命令", "warnings": warnings}


def cmd_gate(a, ctx):
    ctx.require()
    ci, plan = card_info(ctx), load_plan(ctx)
    gates = plan.setdefault("gates", {})
    if a.which in ("A", "AB"):
        errors, warnings_a = card_errors(ci)
        if errors:
            out({"ok": False, "gate": "A", "errors": errors, "warnings": warnings_a,
                 "next": nx(ctx, ("check", "card"), "next.fix_card", n=len(errors))}, 1)
        ha = gate_a_hash(ci)
    if a.which == "A":
        two_step(ctx, "gate-A", ha, a.confirm, gate_a_preview(ci, warnings_a))
        gates["A"] = {"hash": ha, "at": now(), "confirmed_via": "token", "max_fails": ci["max_fails"]}
        gates.pop("B", None)
        commit(ctx, plan, "gate", "闸门 A 通过（决策卡已确认）", gate="A", hash=ha)
        out({"ok": True, "gate": "A", "next": nx(ctx, ("check", "plan"), "next.write_plan")})
    if a.which == "B":
        gs = gate_state(plan, ci)
        if gs["A"] != "valid":
            raise Refuse("闸门 A 未通过或决策卡核心内容已改变，先运行 gate A", gates=gs, next=gate_next(ctx, plan, gs))
        ha = gates["A"]["hash"]
    elif plan.get("risk") == "high":
        raise Refuse("高风险档必须分别确认 gate A 与 gate B：方向和计划各自需要用户看清后同意", 2,
                     next=nx(ctx, ("gate", "A"), "next.gate_a"))
    errors, warnings_b = plan_errors(plan, ci)
    if errors:
        out({"ok": False, "gate": "B", "errors": errors, "warnings": warnings_b,
             "next": nx(ctx, ("check", "plan"), "next.fix_plan", n=len(errors))}, 1)
    hb = plan_hash(plan)
    if a.which == "B":
        two_step(ctx, "gate-B", hb, a.confirm, gate_b_preview(plan, warnings_b))
        msg = "闸门 B 通过（计划已确认）"
    else:
        two_step(ctx, "gate-AB", {"a": ha, "b": hb}, a.confirm,
                 {"决策卡": gate_a_preview(ci, warnings_a), "计划": gate_b_preview(plan, warnings_b),
                  "说明": "一次确认同时通过闸门 A（方向）与闸门 B（计划），并同意执行计划里的验证命令"})
        gates["A"] = {"hash": ha, "at": now(), "confirmed_via": "token", "max_fails": ci["max_fails"]}
        msg = "闸门 A、B 一次确认通过（决策卡与计划）"
    gates["B"] = {"hash": hb, "a_hash": ha, "at": now(), "confirmed_via": "token"}
    commit(ctx, plan, "gate", msg, gate=a.which, hash=hb)
    out({"ok": True, "gate": a.which, "first_step": plan.get("first_step"), "next": light_next(ctx, plan=plan, ci=ci)})


_LAZY = object()        # collect_status 的 fp 参数：需要时才计算指纹


def review_problems(ctx, plan, fp):
    """审查结论对当前计划与代码是否仍然有效；空列表表示有效。status 与 archive 共用同一判断。"""
    review = plan.get("review") or {}
    if review.get("verdict") != "pass":
        return ["以「完成」归档需要交付审查结论为 pass（当前：%s）" % (review.get("verdict") or "无")]
    if review.get("plan_hash") != plan_hash(plan) or (fp is not None and review.get("fingerprint") != fp):
        return ["审查之后计划或代码已改变，需要重新 review"]
    rep = review.get("independent_report")
    if isinstance(rep, dict) and file_sha(ctx.p(REVIEW_REPORT)) != rep.get("sha"):
        return ["审查时关联的独立复核报告 %s 之后被修改或删除，需要重新 review" % rep.get("path")]
    return []


def file_sha(path):
    """普通文件内容的 16 位 sha256；不存在、是符号链接或读不了时返回 None。"""
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return sha(f.read(), 16)
    except OSError:
        return None


def evidence_state(ctx, step, fp, fp_known=True):
    """步骤当前证据的新鲜度：none / unverified / fresh / failed / stale / intact / unknown。"""
    evidence = [e for e in step.get("evidence", []) if isinstance(e, dict)]
    if not evidence:
        return "none"
    if has_verify(step):
        cmds = [e for e in evidence if e.get("kind") == "command"]
        if not cmds:
            return "unverified" if evidence[-1].get("kind") == "note" else "none"
        if not cmds[-1].get("ok"):
            return "failed"
        if not fp_known or fp is None:
            return "unknown"
        return "fresh" if fresh_command_pass(step, fp) else "stale"
    if any(e.get("kind") == "artifact" for e in evidence):
        if artifact_issues(ctx, step, fp if fp_known else None):
            return "stale"
        return "intact" if fp_known and fp is not None else "unknown"
    return "unverified"


def read_archived(ctx):
    """ARCHIVED 标记：(标记 dict 或 None, 是否已同步, 是否损坏)。"""
    if not os.path.exists(ctx.p("ARCHIVED")):
        return None, False, False
    try:
        with open(ctx.p("ARCHIVED"), encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict):
            raise ValueError
        return m, bool(m.get("synced")), False
    except (OSError, ValueError):
        return {}, False, True


def collect_status(ctx, plan=None, ci=None, fp=_LAZY, full=True, tolerate_fp_error=False):
    """一次读取得到 status / brief / handoff / next 共用的快照；不写任何文件，不调用 out()。
    full=False 时不读事件、不做一致性告警；fp=_LAZY 时只在需要判断证据时计算指纹。"""
    plan = plan if plan is not None else load_plan(ctx)
    ci = ci if ci is not None else card_info(ctx)
    steps = plan["steps"]
    gs = gate_state(plan, ci)
    counts = {k: sum(1 for s in steps if s.get("status", "todo") == k) for k in STATUSES}
    review = plan.get("review") or {}
    fp_known, fp_error = True, None
    if fp is _LAZY:
        if full or counts["done"] == len(steps) or review:
            try:
                fp = fingerprint(ctx)
            except Refuse as r:
                if not tolerate_fp_error:
                    raise
                fp, fp_known, fp_error = None, False, r.reason
        else:
            fp, fp_known = None, False
    events, warnings = None, []
    if full:
        events = read_events(ctx)
        warnings = state_warnings(ctx, plan, events)
        seq = 0
        for ev in events:
            try:
                seq = max(seq, int(ev.get("seq", 0)))
            except (TypeError, ValueError):
                pass
        if plan.get("last_event", 0) < seq:
            warnings.append("plan.json 落后于事件日志（最后事件 #%d，计划记录 #%d）：上次写入可能中断，请检查 events.jsonl"
                            % (seq, plan.get("last_event", 0)))
    max_fails = effective_max_fails(plan, ci)
    esc_items = []
    for s in steps:
        sid = sid_key(s.get("id"))
        if s.get("status") == "needs_replan":
            esc_items.append({"kind": "needs_replan", "step": sid, "fails": s.get("fails", 0), "max": max_fails,
                              "tests_assumption": s.get("tests_assumption") or None})
        est, spent = s.get("estimate_h"), s.get("spent_h", 0)
        if isinstance(est, (int, float)) and est > 0 and spent > 2 * est and s.get("status") != "done":
            esc_items.append({"kind": "hours", "step": sid, "spent": spent, "est": est})
    deadline_hit = isinstance(ci["deadline"], dt.date) and dt.date.today() >= ci["deadline"] \
        and counts["done"] < len(steps)
    if deadline_hit:
        esc_items.append({"kind": "deadline", "deadline": str(ci["deadline"]), "trigger": ci["trigger"],
                          "action": ci["action"]})
    stale = {}
    if fp_known:
        for s in steps:
            if s.get("status") == "done":
                reason = stale_verified_step(ctx, s, fp)
                if reason:
                    stale[sid_key(s.get("id"))] = reason
    note_only = [sid_key(s.get("id")) for s in steps if s.get("status") == "done"
                 and s.get("evidence") and all(e.get("kind") == "note" for e in s["evidence"])]
    rproblems = review_problems(ctx, plan, fp) if (review and fp_known) else ["no review"]
    marker, synced, broken = read_archived(ctx)
    if broken:
        warnings.append("ARCHIVED 标记已损坏")
    if marker is not None:
        stage = "ready-to-purge" if synced else "archived"
    elif gs["A"] != "valid":
        stage = "direction"
    elif gs["B"] != "valid":
        stage = "plan"
    elif counts["needs_replan"]:
        stage = "replan"
    elif counts["done"] < len(steps):
        stage = "execute"
    elif rproblems:
        stage = "review"
    else:
        stage = "closeout"
    current, current_reason = pick_current(plan)
    if full and fp is None and fp_known:
        warnings.append("非 git 项目：无法判断证据是否对应当前代码")
    return {"plan": plan, "ci": ci, "fp": fp, "fp_known": fp_known, "fp_error": fp_error, "gates": gs,
            "counts": counts, "stage": stage, "current": current, "current_reason": current_reason, "esc_items": esc_items,
            "deadline_hit": deadline_hit, "stale": stale, "note_only": note_only, "review": review,
            "review_valid": not rproblems, "archived": marker, "synced": synced, "events": events,
            "warnings": warnings, "max_fails": max_fails}


def esc_text_zh(item):
    """status JSON 里沿用的中文升级说明（brief / handoff 用本地化版本）。"""
    if item["kind"] == "needs_replan":
        return ("步骤 %s 已失败 %d 次（上限 %d），待重新规划：修改步骤后 replan，再重新通过 gate B"
                % (item["step"], item["fails"], item["max"])
                + ("；它验证的是假设 %s，先回到定方向重审" % item["tests_assumption"] if item["tests_assumption"] else ""))
    if item["kind"] == "hours":
        return "步骤 %s 已投入 %.1fh，超过预计 %.1fh 的一倍：一级升级，回到计划层" % (item["step"], item["spent"], item["est"])
    return ("已到止损期限 %s（触发状态：%s）：二级升级，对照决策卡判断是否执行动作「%s」"
            % (item["deadline"], item["trigger"], item["action"]))


def status_payload(ctx, snap):
    plan, ci, current, review = snap["plan"], snap["ci"], snap["current"], snap["review"]
    steps = plan["steps"]
    return {"stage": snap["stage"], "gates": snap["gates"], "risk": plan.get("risk", "standard"),
            "current_step": {k: current.get(k) for k in ("id", "title", "done_when", "verify", "verify_cmd",
                                                         "verify_argv", "status")} if current else None,
            "counts": snap["counts"], "total": len(steps),
            "unverified_steps": [sid_key(s.get("id")) for s in steps if s.get("status") == "implemented"],
            "stale_evidence_steps": list(snap["stale"]), "note_only_done_steps": snap["note_only"],
            "review": {"verdict": review.get("verdict"), "valid_for_current_code": snap["review_valid"]}
            if review else None,
            "escalations": [esc_text_zh(x) for x in snap["esc_items"]], "warnings": snap["warnings"],
            "fingerprint": snap["fp"], "kill_deadline": str(ci["deadline"]) if ci["deadline"] else None,
            "other_workspaces": other_workspaces(ctx)}


def other_workspaces(ctx):
    return [w for w in find_workspaces(ctx.root, ctx.git) if os.path.realpath(os.path.join(ctx.root, w)) != ctx.dir]


def cmd_status(a, ctx):
    ctx.require()
    snap = collect_status(ctx)
    out(dict(status_payload(ctx, snap), next=snap_next(ctx, snap)))


def cmd_step(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    s = find_step(plan, a.id)
    old, new = s.get("status", "todo"), a.status
    if old == "needs_replan":
        raise Refuse("步骤 %s 已触发升级，待重新规划：先修改步骤并 replan，或用 replan --waive 记录豁免" % s.get("id"),
                     next=replan_next(ctx, s, effective_max_fails(plan, ci)))
    if old == "done":
        raise Refuse("步骤 %s 已完成；如需重做，用 reopen 记录原因（旧证据会归档）" % s.get("id"),
                     next=nx(ctx, ("reopen", s.get("id"), "--reason", T(ctx, "ph.reason")), "next.reopen", step=s.get("id")))
    if new not in TRANSITIONS[old]:
        allowed = sorted(TRANSITIONS[old])
        to = "in_progress" if "in_progress" in allowed else allowed[0]
        raise Refuse("不允许的状态转换：%s → %s。允许：%s" % (old, new, ", ".join(allowed) or "无"), 2,
                     next=nx(ctx, ("step", s.get("id"), "--status", to), "next.start", step=s.get("id"), title=s.get("title")))
    require_gate_b(ctx, plan, ci)
    if new == "in_progress":
        pending = [d for d in s.get("depends_on", []) if find_step(plan, d).get("status") != "done"]
        if pending:
            raise Refuse("步骤 %s 依赖的步骤 %s 尚未完成" % (s.get("id"), pending),
                         next=nx(ctx, ("status",), "next.wait_dep", step=s.get("id"), deps=pending))
        # 每次从未开始的状态（todo 或 blocked）进入执行都要确认，不能经 blocked 绕过
        if s.get("irreversible") and old in ("todo", "blocked"):
            two_step(ctx, "irreversible", {"step": struct_of(s), "fp": fingerprint(ctx)}, a.confirm,
                     {"步骤": s.get("title"), "警告": "这是不可逆操作，开始前需要用户确认"})
        s.setdefault("started_at", now())
    if a.hours:
        s["spent_h"] = round(float(s.get("spent_h", 0)) + a.hours, 2)
    if new == "done":
        fp = fingerprint(ctx)
        if has_verify(s):
            if not fresh_command_pass(s, fp):
                ev = run_verify(ctx, s, a.timeout, fp_before=fp)
                t = track_verify(plan, ci, s, ev)
                if not ev["ok"]:
                    commit(ctx, plan, "verify", "步骤 #%s 验证未通过（退出码 %s）；%s"
                           % (s.get("id"), ev["exit_code"], count_note(t)),
                           step=s.get("id"), ok=False, exit_code=ev["exit_code"], counted=t["counted"],
                           fails=t["fails"], escalated=t["escalate"])
                    raise Refuse("验证命令未通过（退出码 %s）：%s。未标记完成；%s"
                                 % (ev["exit_code"], ev.get("note") or ev["output_tail"][-300:], count_note(t)),
                                 fails=t["fails"], max_fails=t["max_fails"], counted=t["counted"],
                                 escalate=t["escalate"],
                                 next=replan_next(ctx, s, t["max_fails"]) if t["escalate"]
                                 else nx(ctx, ("step", s.get("id"), "--status", "done"), "next.verify_retry",
                                         fails=t["fails"], max=t["max_fails"]))
        elif a.artifact:
            path = a.artifact if os.path.isabs(a.artifact) else os.path.join(ctx.root, a.artifact)
            if os.path.islink(path) or not os.path.isfile(path) or not inside(path, ctx.root):
                raise Refuse("--artifact 必须是项目内存在的文件：%s" % a.artifact, 2)
            with open(path, "rb") as f:
                digest = sha(f.read(), 16)
            s.setdefault("evidence", []).append({"kind": "artifact", "path": os.path.relpath(os.path.realpath(path), ctx.root),
                                                 "sha": digest, "at": now(), "fingerprint": fp,
                                                 "text": a.evidence or ""})
        elif (a.evidence or "").strip():
            if plan.get("risk") == "high":
                raise Refuse("高风险计划不接受纯文字证据：给步骤加验证命令（verify_argv / verify_cmd），或用 --artifact 指向证据文件",
                             next=finish_next(ctx, plan, s))
            s.setdefault("evidence", []).append({"kind": "note", "text": a.evidence.strip(), "at": now(),
                                                 "fingerprint": fp, "verified": False})
        else:
            raise Refuse("没有证据不能标记完成。可用：验证命令 verify_argv / verify_cmd（脚本执行）、--artifact 文件、"
                         "或 --evidence 文字（仅标准档，记为未验证）；尚未验证就用 implemented",
                         next=finish_next(ctx, plan, s))
        s["finished_at"] = now()
    s["status"] = new
    commit(ctx, plan, "step", "步骤 #%s %s → %s%s" % (s.get("id"), STATUS_ZH[old], STATUS_ZH[new],
                                                     ("；" + a.note) if a.note else ""),
           step=s.get("id"), frm=old, to=new, note=a.note)
    last = s["evidence"][-1] if new == "done" and s.get("evidence") else None
    out({"ok": True, "step": s.get("id"), "from": old, "to": new,
         "evidence_kind": last.get("kind") if last else None,
         "evidence_verified": (last.get("kind") in ("command", "artifact")) if last else None,
         "next": light_next(ctx, plan, ci, fp=fp if new == "done" else _LAZY)})


def cmd_verify(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    if not a.all and not a.id:
        raise Refuse("给出步骤 ID 或 --all", 2)
    require_gate_b(ctx, plan, ci)
    targets = [s for s in plan["steps"] if has_verify(s)] if a.all \
        else [find_step(plan, a.id)]
    results, fp = [], fingerprint(ctx)
    for s in targets:
        ev = run_verify(ctx, s, a.timeout, fp_before=fp)
        fp = ev["fingerprint"]           # 本步结束时的指纹就是下一步开始时的指纹
        t = track_verify(plan, ci, s, ev)
        results.append({"step": s.get("id"), "ok": ev["ok"], "exit_code": ev["exit_code"],
                        "seconds": ev["seconds"], "note": ev.get("note"), "counted": t["counted"],
                        "fails": t["fails"], "escalated": t["escalate"]})
    commit(ctx, plan, "verify", "执行验证：%s" % (", ".join(
        "#%s %s" % (r["step"], "通过" if r["ok"] else "失败" + ("，已升级" if r["escalated"] else "，计入失败" if r["counted"] else ""))
        for r in results) or "无"), results=results)
    ok = all(r["ok"] for r in results)
    escalated = next((s for s, r in zip(targets, results) if r["escalated"]), None)
    bad = next((s for s, r in zip(targets, results) if not r["ok"]), None)
    out({"ok": ok, "results": results, "fingerprint": fp,
         "next": replan_next(ctx, escalated, effective_max_fails(plan, ci)) if escalated is not None
         else light_next(ctx, plan, ci, fp=fp) if bad is None
         else nx(ctx, ("verify", bad.get("id")), "next.verify_retry", fails=bad.get("fails", 0),
                 max=effective_max_fails(plan, ci))}, 0 if ok else 1)


def cmd_fail(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    s = find_step(plan, a.id)
    if s.get("status") in ("done", "needs_replan"):
        raise Refuse("步骤 %s 当前为 %s，不能记录失败" % (s.get("id"), STATUS_ZH[s.get("status")]))
    if a.hours:
        s["spent_h"] = round(float(s.get("spent_h", 0)) + a.hours, 2)
    try:
        fp = fingerprint(ctx)
    except Refuse:
        fp = None
    mark = s.get("fail_mark") if isinstance(s.get("fail_mark"), dict) else {}
    if fp is not None and mark.get("by") == "auto" and mark.get("fp") == fp and not mark.get("absorbed"):
        # 这次失败脚本已经在验证时自动计过；手动报告只记录说明，不重复计数（且只吸收一次）
        s["fail_mark"] = dict(mark, absorbed=True)
        max_fails = effective_max_fails(plan, ci)
        commit(ctx, plan, "fail", "步骤 #%s 的这次失败已由脚本自动计入（第 %d 次），不重复计数：%s"
               % (s.get("id"), s.get("fails", 0), a.note), step=s.get("id"), fails=s.get("fails", 0),
               note=a.note, escalated=False, counted=False)
        out({"ok": True, "step": s.get("id"), "fails": s.get("fails", 0), "max_fails": max_fails, "escalate": False,
             "counted": False, "status": s["status"],
             "next": nx(ctx, ("step", s.get("id"), "--status", "done") if has_verify(s) else None, "next.verify_retry",
                        fails=s.get("fails", 0), max=max_fails)})
    s["fails"] = int(s.get("fails", 0)) + 1
    s["fail_mark"] = {"fp": fp, "by": "manual", "at": now(), "absorbed": False}
    esc, max_fails = escalate_step(plan, ci, s, "manual")
    commit(ctx, plan, "fail", "步骤 #%s 验证失败（第 %d 次）：%s%s" % (s.get("id"), s["fails"], a.note,
                                                              "；触发一级升级，待重新规划" if esc else ""),
           step=s.get("id"), fails=s["fails"], note=a.note, escalated=esc, counted=True)
    out({"ok": True, "step": s.get("id"), "fails": s["fails"], "max_fails": max_fails, "escalate": esc,
         "counted": True, "status": s["status"],
         "next": replan_next(ctx, s, max_fails) if esc
         else nx(ctx, ("step", s.get("id"), "--status", "done") if has_verify(s) else None, "next.verify_retry",
                 fails=s["fails"], max=max_fails)})


def cmd_replan(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    s = find_step(plan, a.id)
    if s.get("status") != "needs_replan":
        raise Refuse("步骤 %s 不在待重新规划状态" % s.get("id"), 2)
    esc = s.get("escalation") or {}
    changed = sha(struct_of(s), 16) != esc.get("struct_hash")
    if a.waive:
        two_step(ctx, "waive", {"step": struct_of(s), "fails": s.get("fails"), "reason": a.waive}, a.confirm,
                 {"步骤": s.get("title"), "失败次数": s.get("fails"), "豁免理由": a.waive,
                  "后果": "不修改计划继续尝试；再失败一次会立即再次升级"})
        s["fails"] = max(0, effective_max_fails(plan, ci) - 1)
        s.setdefault("waivers", []).append({"at": now(), "reason": a.waive})
    elif not changed:
        raise Refuse("步骤 %s 的内容（标题/完成判据/验证方法/验证命令/依赖等）自升级以来没有修改。"
                     "先在 plan.json 里修改此步骤；确有理由不改，用 --waive 理由" % s.get("id"))
    else:
        s["fails"] = 0
        s.pop("last_verify", None)      # 重新规划后从新的基线开始计数
        s.pop("fail_mark", None)
    s["status"] = esc.get("prev_status") if esc.get("prev_status") in ("todo", "blocked") else "todo"
    s.setdefault("escalation_history", []).append(dict(esc, resolved_at=now(),
                                                       resolution="waived" if a.waive else "replanned"))
    s.pop("escalation", None)
    commit(ctx, plan, "replan", "步骤 #%s %s：%s" % (s.get("id"), "豁免继续" if a.waive else "已重新规划", a.note),
           step=s.get("id"), waived=bool(a.waive), note=a.note)
    gs = gate_state(plan, ci)
    out({"ok": True, "step": s.get("id"), "status": s["status"], "gates": gs,
         "next": gate_next(ctx, plan, gs) if gs["B"] != "valid"
         else nx(ctx, ("step", s.get("id"), "--status", "in_progress"), "next.start", step=s.get("id"), title=s.get("title"))})


def cmd_reopen(a, ctx):
    ctx.require()
    plan = load_plan(ctx)
    s = find_step(plan, a.id)
    if s.get("status") != "done":
        raise Refuse("只有已完成的步骤可以 reopen", 2)
    s.setdefault("evidence_history", []).append({"reopened_at": now(), "reason": a.reason,
                                                 "evidence": s.get("evidence", [])})
    s["evidence"] = []
    s["status"] = "todo"
    s.pop("finished_at", None)
    s.pop("last_verify", None)          # 重做从新的基线开始；失败次数保留
    plan.pop("review", None)
    commit(ctx, plan, "reopen", "步骤 #%s 重新打开：%s（旧证据已归档，审查结论作废）" % (s.get("id"), a.reason),
           step=s.get("id"), reason=a.reason)
    out({"ok": True, "step": s.get("id"), "status": "todo", "review_invalidated": True,
         "next": nx(ctx, ("step", s.get("id"), "--status", "in_progress"), "next.start", step=s.get("id"),
                    title=s.get("title"))})


def retro_problems(ctx):
    path = ctx.p("retro.md")
    if not os.path.exists(path):
        return ["缺少 retro.md：先按 stage-4-review.md 完成复盘"]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sec, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = canonical_section(m.group(1))
            sec[cur] = []
        elif cur is not None:
            sec[cur].append(line)
    return ["复盘章节「%s」为空或只有模板占位" % k for k in RETRO_SECTIONS if not meaningful(sec.get(k, []))]


def cmd_review(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    require_gate_b(ctx, plan, ci)
    fp = fingerprint(ctx)
    problems = []
    if a.verdict == "pass":
        notdone = [sid_key(s.get("id")) for s in plan["steps"] if s.get("status") != "done"]
        if notdone:
            problems.append("还有未完成的步骤 %s" % notdone)
        stale = [(sid_key(s.get("id")), stale_verified_step(ctx, s, fp)) for s in plan["steps"]]
        stale = [(sid, reason) for sid, reason in stale if reason]
        if stale:
            problems.append("步骤存在失效的命令/文件证据：%s；重新验证或 reopen 后更新证据" % stale)
        if plan.get("risk") == "high":
            weak = [sid_key(s.get("id")) for s in plan["steps"]
                    if all(e.get("kind") == "note" for e in s.get("evidence", []))]
            if weak:
                problems.append("高风险计划中步骤 %s 只有文字证据" % weak)
        if a.blocker:
            problems.append("结论为 pass 时不能有阻断项；有阻断项请用 fix 或 fail")
    if problems:
        out({"ok": False, "verdict": a.verdict, "problems": problems,
             "next": nx(ctx, None, "next.fix_problems") if a.blocker else light_next(ctx, plan, ci, fp=fp)}, 3)
    report = None
    if a.independent_report:
        path = ctx.p(REVIEW_REPORT)
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) < REPORT_MIN_BYTES:
            raise Refuse("--independent-report 需要工作区里的 %s（普通文件，至少 %d 字节；模板见 assets/%s）"
                         % (REVIEW_REPORT, REPORT_MIN_BYTES, REVIEW_REPORT), 2,
                         next=nx(ctx, None, "next.fix_problems"))
        report = {"path": (ctx.rel + "/" + REVIEW_REPORT).replace(os.sep, "/"), "sha": file_sha(path)}
    payload = {"verdict": a.verdict, "blockers": a.blocker, "plan": plan_hash(plan), "fp": fp, "report": report}
    two_step(ctx, "review", payload, a.confirm,
             {"结论": a.verdict, "阻断项": a.blocker, "独立复核报告": report["path"] if report else None,
              "步骤证据": [{"id": s.get("id"), "最后证据类型": (s.get("evidence") or [{}])[-1].get("kind")}
                       for s in plan["steps"]]})
    plan["review"] = {"verdict": a.verdict, "blockers": a.blocker, "at": now(), "fingerprint": fp,
                      "plan_hash": plan_hash(plan), "confirmed_via": "token",
                      "note": "confirmed_via=token 表示内容经两步确认；脚本无法证明确认者是人"}
    if report:
        plan["review"]["independent_report"] = report      # 只防事后篡改，不能证明复核者真的独立
    commit(ctx, plan, "review", "交付审查结论：%s%s" % (a.verdict, "；阻断项：" + "；".join(a.blocker) if a.blocker else ""),
           verdict=a.verdict, blockers=a.blocker)
    out({"ok": True, "verdict": a.verdict,
         "next": light_next(ctx, plan, ci, fp=fp) if a.verdict == "pass"
         else nx(ctx, ("check", "plan"), "next.review_fix") if a.verdict == "fix"
         else nx(ctx, ("archive", "--outcome", stop_outcome(ctx)), "next.review_fail")})


def cell(x):
    return str(x if x is not None else "").replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def card_title(ci):
    m = re.search(r"^#\s*(?:决策卡|decision card)[:：]\s*(.+)$", ci["text"], re.M | re.I)
    return m.group(1).strip() if m else "未命名决策"


def strip_h1(text):
    return re.sub(r"\A\s*#\s[^\n]*\n", "", text, count=1).strip()


LABELS = {
    "zh": {"title": "# 决策记录：%s", "outcome": "- 结局：%s", "date": "- 归档日期：%s", "sync_pending": "- 知识同步：待完成",
           "review": "- 审查结论：%s", "none": "无", "review_report": "- 独立复核报告：%s（sha %s）",
           "note": "- 说明：本文件是历史记录，描述当时为什么这样决定；系统现状以 README 与 docs 为准。",
           "card": "## 决策卡（归档时版本）", "exec": "## 执行摘要", "retro": "## 复盘",
           "table": ["| # | 步骤 | 状态 | 证据类型 | 证据 |", "|---|---|---|---|---|"],
           "cmd_ev": "`%s` 退出码 %s（代码 %s）", "art_ev": "%s（sha %s）", "note_ev": "%s（未验证）",
           "sync": "- 知识同步：", "sync_done": "已完成（%s；本次执行静态审计 error 0、warn %s；其他证据层级见下方报告）",
           "sync_report": "## 知识同步报告", "purged": "- 工作区：已于 %s 删除（可从 git 历史恢复）",
           "outcomes": {"完成": "完成", "止损": "止损", "放弃": "放弃"}, "status": STATUS_ZH},
    "en": {"title": "# Decision record: %s", "outcome": "- Outcome: %s", "date": "- Archived: %s",
           "sync_pending": "- Knowledge sync: pending", "review": "- Review verdict: %s", "none": "none",
           "review_report": "- Independent review report: %s (sha %s)",
           "note": "- Note: this is a historical record of why the decision was made; README and docs describe the "
                   "current system.",
           "card": "## Decision card (as archived)", "exec": "## Execution summary", "retro": "## Retro",
           "table": ["| # | Step | Status | Evidence kind | Evidence |", "|---|---|---|---|---|"],
           "cmd_ev": "`%s` exit code %s (code %s)", "art_ev": "%s (sha %s)", "note_ev": "%s (unverified)",
           "sync": "- Knowledge sync: ",
           "sync_done": "done (%s; static audit run by sync: error 0, warn %s; other evidence levels in the report below)",
           "sync_report": "## Knowledge sync report", "purged": "- Workspace: deleted on %s (recoverable from git history)",
           "outcomes": {"完成": "done", "止损": "stopped", "放弃": "abandoned"}, "status": STATUS_EN},
}
# 新增输出（next.why、status --brief、handoff）的中英文文案；旧的拒绝原因仍是中文。
MESSAGES = {
    "zh": {
        "ph.note": "<说明>", "ph.evidence": "<证据>", "ph.artifact": "<证据文件>", "ph.reason": "<原因>",
        "ph.blocker": "<阻断项>",
        "next.fill_card": "填写 decision-card.md，然后检查决策卡",
        "next.fix_card": "决策卡还有 {n} 处错误：按 check card 的提示修改后再检查",
        "next.gate_a": "决策卡已通过检查：把预览给用户看，用户同意后确认方向（闸门 A）",
        "next.gate_ab": "标准档，决策卡和计划都已通过检查：把预览给用户看，一次确认方向与计划",
        "next.write_plan": "方向已确认：编写 plan.json，然后检查计划",
        "next.fix_plan": "计划还有 {n} 处错误：按 check plan 的提示修改后再检查",
        "next.gate_b": "计划已通过检查：把预览（含将执行的验证命令）给用户看，用户同意后确认计划（闸门 B）",
        "next.replan_changed": "步骤 {step} 已修改：先解除升级，再重新确认计划",
        "next.edit_step": "步骤 {step} 失败 {fails}/{max} 次已升级：在 plan.json 修改它（拆小、换做法、补前置步骤）后运行 replan；"
                          "不修改而继续，需与用户商量后用 --waive",
        "next.assumption": "；它检验的是假设 {a}，先回到定方向重审这条假设",
        "next.deadline": "已到止损期限 {deadline}：和用户对照决策卡决定是否执行「{action}」；决定停止就以止损归档",
        "next.start": "开始步骤 {step}：{title}",
        "next.start_irreversible": "开始不可逆步骤 {step}：{title}（脚本会先要求用户确认）",
        "next.unblock": "步骤 {step} 处于阻塞：解除阻塞原因后继续",
        "next.wait_dep": "步骤 {step} 依赖的步骤 {deps} 尚未完成",
        "next.finish_cmd": "完成步骤 {step}：脚本会运行验证命令，通过才算完成",
        "next.finish_note": "完成步骤 {step}：它没有验证命令，给出证据（标准档的文字证据记为未验证）",
        "next.finish_artifact": "完成步骤 {step}：高风险档需要命令或文件证据",
        "next.verify_retry": "验证未通过（已计失败 {fails}/{max}）：查明原因、修改后再试",
        "next.verify_all": "审查前重新验证：步骤 {steps} 的命令证据已不对应当前代码",
        "next.reopen": "步骤 {step} 的证据文件已变化：reopen 后重新完成",
        "next.review_pass": "全部步骤已完成：按 stage-4 审查，把预览给用户看后记录审查结论",
        "next.review_fix": "审查结论为 fix：把阻断项写成新步骤加入 plan.json，再检查计划",
        "next.review_fail": "审查结论为 fail：和用户决定回到哪一级；决定停止就以止损归档",
        "next.retro": "先写完复盘 retro.md（{problems}），再归档",
        "next.closeout": "审查已通过：closing-out 写好收尾报告后，一步完成归档与知识同步（先预览）",
        "next.archive": "审查已通过：归档为决策记录（先预览）",
        "next.sync": "已归档：closing-out 写好收尾报告后登记知识同步",
        "next.purge": "已同步：提交全部改动后，预览删除工作区",
        "next.purge_done": "提交这次删除；装了 closing-out 的话再审计一次",
        "next.confirm": "把预览给用户看；用户明确同意后才运行这条命令",
        "next.confirm_mismatch": "内容已变化：重新运行不带 --confirm 的命令，查看最新预览",
        "next.apply": "把预览给用户看；用户同意后加 --apply 执行",
        "next.fix_problems": "先解决上面列出的问题",
        "next.status": "查看当前阶段和下一步",
        "next.init": "这里还没有工作区：需要时先创建",
        "next.fix_dir": "在项目目录内运行，或修正 --dir / DE_WORKSPACE",
        "brief.head": "[de] {rel} · {title} · 阶段 {stage} · 闸门 {gates} · {risk}",
        "brief.steps": "步骤 {done}/{total} 完成",
        "brief.current": "；当前 #{id} {title}（{status}，失败 {fails}/{max}）",
        "brief.esc": "升级：{text}",
        "brief.stale": "证据已过期：{ids}", "brief.note_only": "只有文字证据：{ids}",
        "brief.fp_unavailable": "代码指纹不可用，证据新鲜度未知：{err}",
        "brief.next": "下一步：{cmd} — {why}",
        "brief.others": "其他工作区：{list}", "brief.archived_tag": "（已归档）", "brief.more": "等共 {n} 个",
        "brief.details": "详情：{status} / {handoff}",
        "brief.no_selected": "[de] 当前没有选中工作区；本仓库已有：{list}。用 --dir 或 DE_WORKSPACE 选择",
        "brief.error": "[de] 工作区状态读取失败：{err}",
        "brief.archived": "已归档为 {record}；知识同步：{synced}", "yes": "已完成", "no": "未完成",
        "esc.needs_replan": "步骤 {step} 失败 {fails}/{max} 次，待重新规划",
        "esc.hours": "步骤 {step} 已投入 {spent}h，超过预计 {est}h 的一倍",
        "esc.deadline": "已到止损期限 {deadline}（触发状态：{trigger}）",
        "gate.valid": "有效", "gate.stale": "已失效", "gate.missing": "未通过",
        "fresh.none": "无证据", "fresh.unverified": "未验证（文字）", "fresh.fresh": "新鲜", "fresh.failed": "最近一次失败",
        "fresh.stale": "已过期", "fresh.intact": "文件完好", "fresh.unknown": "未知",
        "handoff.title": "# 交接摘要：{title}",
        "handoff.meta": "- 工作区：`{rel}`\n- 结论：{verdict}\n- 阶段：{stage}；闸门 A {a}、B {b}；风险档位：{risk}\n- 止损期限：{deadline}",
        "handoff.fp_unavailable": "- 注意：代码指纹不可用（{err}），证据新鲜度未知",
        "handoff.steps": "## 步骤",
        "handoff.steps_head": "| # | 步骤 | 状态 | 证据类型 | 新鲜度 | 失败 |",
        "handoff.note_only": "## 只有文字证据的已完成步骤", "handoff.esc": "## 升级",
        "handoff.assumptions": "## 关键假设", "handoff.assumptions_head": "| # | 假设 | 状态 | 由哪些步骤检验 |",
        "handoff.criteria": "## 成功标准覆盖", "handoff.criteria_head": "| # | 标准 | 状态 |",
        "handoff.events": "## 最近事件", "handoff.next": "## 下一步",
        "handoff.files": "## 相关文件（只列路径；需要内容时直接读文件）", "handoff.none": "无",
    },
    "en": {
        "ph.note": "<note>", "ph.evidence": "<evidence>", "ph.artifact": "<evidence file>", "ph.reason": "<reason>",
        "ph.blocker": "<blocker>",
        "next.fill_card": "Fill in decision-card.md, then check the card",
        "next.fix_card": "The decision card still has {n} errors: fix them as check card reports, then check again",
        "next.gate_a": "The card passes its checks: show the preview to the user and confirm the direction (gate A) once they agree",
        "next.gate_ab": "Standard tier and both card and plan pass their checks: show the preview and confirm direction and plan together",
        "next.write_plan": "Direction confirmed: write plan.json, then check the plan",
        "next.fix_plan": "The plan still has {n} errors: fix them as check plan reports, then check again",
        "next.gate_b": "The plan passes its checks: show the preview (including the verify commands) and confirm the plan (gate B) once the user agrees",
        "next.replan_changed": "Step {step} has been edited: clear the escalation, then re-confirm the plan",
        "next.edit_step": "Step {step} failed {fails}/{max} times and escalated: edit it in plan.json (split it, change approach, add a prerequisite), "
                          "then run replan; to continue unchanged, agree it with the user and use --waive",
        "next.assumption": "; it tests assumption {a}, so revisit that assumption first",
        "next.deadline": "The stop-loss deadline {deadline} has passed: decide with the user whether to take the action \"{action}\"; "
                         "if stopping, archive as stopped",
        "next.start": "Start step {step}: {title}",
        "next.start_irreversible": "Start irreversible step {step}: {title} (the script asks for user confirmation first)",
        "next.unblock": "Step {step} is blocked: resolve the blocker, then continue",
        "next.wait_dep": "Step {step} depends on unfinished steps {deps}",
        "next.finish_cmd": "Finish step {step}: the script runs its verify command and only a pass counts",
        "next.finish_note": "Finish step {step}: it has no verify command, so give evidence (text evidence is recorded as unverified)",
        "next.finish_artifact": "Finish step {step}: the high-risk tier needs command or file evidence",
        "next.verify_retry": "Verification failed (counted failures {fails}/{max}): find the cause, change something, then retry",
        "next.verify_all": "Re-verify before review: command evidence for steps {steps} no longer matches the code",
        "next.reopen": "Step {step}'s evidence file changed: reopen it and finish it again",
        "next.review_pass": "All steps are done: review per stage-4, show the preview to the user, then record the verdict",
        "next.review_fix": "Review verdict is fix: add the blockers to plan.json as new steps, then check the plan",
        "next.review_fail": "Review verdict is fail: decide with the user which level to return to; if stopping, archive as stopped",
        "next.retro": "Finish retro.md first ({problems}), then archive",
        "next.closeout": "Review passed: once closing-out has written its report, archive and sync in one step (preview first)",
        "next.archive": "Review passed: archive as a decision record (preview first)",
        "next.sync": "Archived: once closing-out has written its report, register the knowledge sync",
        "next.purge": "Synced: commit everything, then preview deleting the workspace",
        "next.purge_done": "Commit the deletion; if closing-out is installed, audit once more",
        "next.confirm": "Show the preview to the user; run this command only after they clearly agree",
        "next.confirm_mismatch": "The content changed: rerun without --confirm to see the current preview",
        "next.apply": "Show the preview to the user; once they agree, rerun with --apply",
        "next.fix_problems": "Resolve the problems listed above first",
        "next.status": "See the current stage and next step",
        "next.init": "There is no workspace here yet: create one if needed",
        "next.fix_dir": "Run inside the project, or fix --dir / DE_WORKSPACE",
        "brief.head": "[de] {rel} · {title} · stage {stage} · gates {gates} · {risk}",
        "brief.steps": "steps {done}/{total} done",
        "brief.current": "; current #{id} {title} ({status}, fails {fails}/{max})",
        "brief.esc": "escalation: {text}",
        "brief.stale": "stale evidence: {ids}", "brief.note_only": "text-only evidence: {ids}",
        "brief.fp_unavailable": "code fingerprint unavailable, evidence freshness unknown: {err}",
        "brief.next": "next: {cmd} — {why}",
        "brief.others": "other workspaces: {list}", "brief.archived_tag": " (archived)", "brief.more": "{n} in total",
        "brief.details": "details: {status} / {handoff}",
        "brief.no_selected": "[de] no workspace selected; this repo has: {list}. Select one with --dir or DE_WORKSPACE",
        "brief.error": "[de] could not read the workspace status: {err}",
        "brief.archived": "archived as {record}; knowledge sync: {synced}", "yes": "done", "no": "pending",
        "esc.needs_replan": "step {step} failed {fails}/{max} times and needs replanning",
        "esc.hours": "step {step} has taken {spent}h, more than twice the {est}h estimate",
        "esc.deadline": "the stop-loss deadline {deadline} has passed (trigger: {trigger})",
        "gate.valid": "valid", "gate.stale": "stale", "gate.missing": "not passed",
        "fresh.none": "no evidence", "fresh.unverified": "unverified (text)", "fresh.fresh": "fresh",
        "fresh.failed": "last run failed", "fresh.stale": "stale", "fresh.intact": "file intact", "fresh.unknown": "unknown",
        "handoff.title": "# Handoff: {title}",
        "handoff.meta": "- Workspace: `{rel}`\n- Verdict: {verdict}\n- Stage: {stage}; gate A {a}, gate B {b}; risk tier: {risk}\n"
                        "- Stop-loss deadline: {deadline}",
        "handoff.fp_unavailable": "- Note: code fingerprint unavailable ({err}); evidence freshness unknown",
        "handoff.steps": "## Steps",
        "handoff.steps_head": "| # | Step | Status | Evidence kind | Freshness | Fails |",
        "handoff.note_only": "## Done steps with text-only evidence", "handoff.esc": "## Escalations",
        "handoff.assumptions": "## Key assumptions", "handoff.assumptions_head": "| # | Assumption | Status | Tested by |",
        "handoff.criteria": "## Success criteria coverage", "handoff.criteria_head": "| # | Criterion | Status |",
        "handoff.events": "## Recent events", "handoff.next": "## Next",
        "handoff.files": "## Files (paths only; read them directly for content)", "handoff.none": "none",
    },
}


def T(ctx, key, **kw):
    lang = ctx.lang() if ctx is not None else "zh"
    tpl = MESSAGES.get(lang, {}).get(key) or MESSAGES["zh"][key]
    return tpl.format(**kw)


def nx(ctx, parts, key, needs_user=False, **kw):
    """下一步：cmd 是可直接运行的 de.py 命令（None 表示下一步是人或 Agent 的工作），why 说明原因。"""
    d = {"cmd": de_cmd(ctx, *parts) if parts is not None else None, "why": T(ctx, key, **kw)}
    if needs_user:
        d["needs_user"] = True
    return d


def rel_cwd(path):
    try:
        return os.path.relpath(path, os.getcwd()).replace(os.sep, "/")
    except ValueError:
        return path


def report_arg(ctx):
    return rel_cwd(ctx.p("closeout-report.md"))


def stop_outcome(ctx):
    return "stopped" if ctx.lang() == "en" else "止损"


def closing_out_installed():
    return os.path.isfile(os.path.join(os.path.dirname(SKILL_DIR), "closing-out", "scripts", "audit.py"))


def pick_current(plan):
    """当前应处理的步骤与原因：in_progress > implemented > 依赖已满足的 todo（尚未开工时优先 first_step）
    > blocked > 依赖未满足的 todo。"""
    steps = plan["steps"]
    done = {sid_key(s.get("id")) for s in steps if s.get("status") == "done"}
    for status in ("in_progress", "implemented"):
        s = next((x for x in steps if x.get("status") == status), None)
        if s:
            return s, status
    todo = [s for s in steps if s.get("status", "todo") == "todo"]
    ready = [s for s in todo if all(sid_key(d) in done for d in s.get("depends_on", []))]
    if ready:
        started = any(s.get("started_at") or s.get("status", "todo") != "todo" for s in steps)
        first = next((s for s in ready if sid_key(s.get("id")) == sid_key(plan.get("first_step"))), None)
        return (first if first and not started else ready[0]), "ready"
    s = next((x for x in steps if x.get("status") == "blocked"), None)
    if s:
        return s, "blocked"
    if todo:
        return todo[0], "waiting"
    return None, None


def replan_next(ctx, s, max_fails):
    esc = s.get("escalation") or {}
    if sha(struct_of(s), 16) != esc.get("struct_hash"):
        return nx(ctx, ("replan", s.get("id"), "--note", T(ctx, "ph.note")), "next.replan_changed", step=s.get("id"))
    d = nx(ctx, None, "next.edit_step", step=s.get("id"), fails=s.get("fails", 0), max=max_fails)
    if s.get("tests_assumption"):
        d["why"] += T(ctx, "next.assumption", a=s["tests_assumption"])
    return d


def finish_next(ctx, plan, s):
    if has_verify(s):
        return nx(ctx, ("step", s.get("id"), "--status", "done"), "next.finish_cmd", step=s.get("id"))
    if plan.get("risk") == "high":
        return nx(ctx, ("step", s.get("id"), "--status", "done", "--artifact", T(ctx, "ph.artifact")),
                  "next.finish_artifact", step=s.get("id"))
    return nx(ctx, ("step", s.get("id"), "--status", "done", "--evidence", T(ctx, "ph.evidence")),
              "next.finish_note", step=s.get("id"))


def gate_next(ctx, plan, gs):
    if gs["A"] != "valid":
        which = "AB" if plan.get("risk", "standard") == "standard" else "A"
        return nx(ctx, ("gate", which), "next.gate_ab" if which == "AB" else "next.gate_a")
    return nx(ctx, ("gate", "B"), "next.gate_b")


def next_action(ctx, snap, extras):
    """由快照推出下一个合法动作。extras 里是按阶段补算的检查结果（卡片/计划错误、复盘问题等）。"""
    stage, plan, ci = snap["stage"], snap["plan"], snap["ci"]
    steps, risk = plan["steps"], plan.get("risk", "standard")
    if stage == "ready-to-purge":
        return nx(ctx, ("purge",), "next.purge")
    if stage == "archived":
        return nx(ctx, ("sync", "--report", report_arg(ctx)), "next.sync")
    if stage == "direction":
        if extras.get("card_errors"):
            return nx(ctx, ("check", "card"), "next.fix_card", n=len(extras["card_errors"]))
        if risk == "standard" and not extras.get("plan_errors"):
            return nx(ctx, ("gate", "AB"), "next.gate_ab")
        return nx(ctx, ("gate", "A"), "next.gate_a")
    if stage == "plan":
        for s in steps:
            if s.get("status") == "needs_replan" and sha(struct_of(s), 16) != (s.get("escalation") or {}).get("struct_hash"):
                return replan_next(ctx, s, snap["max_fails"])
        if extras.get("plan_errors"):
            return nx(ctx, ("check", "plan"), "next.fix_plan", n=len(extras["plan_errors"]))
        return nx(ctx, ("gate", "B"), "next.gate_b")
    if snap["deadline_hit"] and stage in ("replan", "execute"):
        return nx(ctx, None, "next.deadline", deadline=ci["deadline"], action=ci["action"])
    if stage == "replan":
        s = next(x for x in steps if x.get("status") == "needs_replan")
        return replan_next(ctx, s, snap["max_fails"])
    if stage == "execute":
        s, reason = snap.get("current"), snap.get("current_reason")
        if reason in ("in_progress", "implemented"):
            return finish_next(ctx, plan, s)
        if reason == "ready":
            return nx(ctx, ("step", s.get("id"), "--status", "in_progress"),
                      "next.start_irreversible" if s.get("irreversible") else "next.start",
                      step=s.get("id"), title=s.get("title"))
        if reason == "blocked":
            return nx(ctx, ("step", s.get("id"), "--status", "in_progress"), "next.unblock", step=s.get("id"))
        if s is not None:
            done = {sid_key(x.get("id")) for x in steps if x.get("status") == "done"}
            deps = [d for d in s.get("depends_on", []) if sid_key(d) not in done]
            return nx(ctx, ("status",), "next.wait_dep", step=s.get("id"), deps=deps)
        return nx(ctx, ("status",), "next.status")
    if stage == "review":
        review = snap["review"]
        if review.get("verdict") == "fix":
            return nx(ctx, ("check", "plan"), "next.review_fix")
        if review.get("verdict") == "fail":
            return nx(ctx, ("archive", "--outcome", stop_outcome(ctx)), "next.review_fail")
        stale_cmd = [sid for sid in snap["stale"] if has_verify(find_step(plan, sid))]
        if stale_cmd:
            return nx(ctx, ("verify", "--all"), "next.verify_all", steps=stale_cmd)
        for sid in snap["stale"]:
            return nx(ctx, ("reopen", sid, "--reason", T(ctx, "ph.reason")), "next.reopen", step=sid)
        return nx(ctx, ("review", "--verdict", "pass"), "next.review_pass")
    # closeout
    if extras.get("retro"):
        return nx(ctx, None, "next.retro", problems="；".join(extras["retro"]))
    if extras.get("closing_out"):
        return nx(ctx, ("closeout", "--report", report_arg(ctx)), "next.closeout")
    return nx(ctx, ("archive",), "next.archive")


def snap_next(ctx, snap):
    """按阶段补算 next_action 需要的检查，再求下一步。"""
    extras, stage = {}, snap["stage"]
    if stage == "direction":
        extras["card_errors"] = card_errors(snap["ci"])[0]
        if not extras["card_errors"]:
            extras["plan_errors"] = plan_errors(snap["plan"], snap["ci"])[0]
    elif stage == "plan":
        extras["plan_errors"] = plan_errors(snap["plan"], snap["ci"])[0]
    elif stage == "closeout":
        extras["retro"] = retro_problems(ctx)
        extras["closing_out"] = closing_out_installed()
    return next_action(ctx, snap, extras)


def utf8_stdout():
    """文本输出（brief、handoff）在 Windows 管道里默认是本地代码页，统一成 UTF-8。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def esc_text(ctx, item):
    if item["kind"] == "needs_replan":
        return T(ctx, "esc.needs_replan", step=item["step"], fails=item["fails"], max=item["max"])
    if item["kind"] == "hours":
        return T(ctx, "esc.hours", step=item["step"], spent=item["spent"], est=item["est"])
    return T(ctx, "esc.deadline", deadline=item["deadline"], trigger=item["trigger"])


def status_label(ctx, status):
    return (STATUS_EN if ctx.lang() == "en" else STATUS_ZH).get(status, status)


def short(text, n=40):
    text = str(text or "").replace("\n", " ")
    return text if len(text) <= n else text[:n - 1] + "…"


BRIEF_MAX_LINES, BRIEF_MAX_CHARS = 15, 1500


def brief_lines(ctx):
    """会话钩子用的简要状态。没有工作区时返回空列表（钩子什么都不注入）。"""
    if not os.path.isfile(ctx.p(MARKER)):
        others = find_workspaces(ctx.root, True) if ctx.git else []
        return [T(ctx, "brief.no_selected", list=", ".join(others[:5]))] if others else []
    snap = collect_status(ctx, full=False, tolerate_fp_error=True)
    plan, ci, gs = snap["plan"], snap["ci"], snap["gates"]
    gates = "A%s B%s" % ("✓" if gs["A"] == "valid" else "✗", "✓" if gs["B"] == "valid" else "✗")
    lines = [T(ctx, "brief.head", rel=ctx.rel.replace(os.sep, "/"), title=short(card_title(ci)), stage=snap["stage"],
               gates=gates, risk=plan.get("risk", "standard"))]
    if snap["archived"] is not None:
        lines.append(T(ctx, "brief.archived", record=snap["archived"].get("record"),
                       synced=T(ctx, "yes" if snap["synced"] else "no")))
    else:
        line = T(ctx, "brief.steps", done=snap["counts"]["done"], total=len(plan["steps"]))
        cur = snap["current"]
        if cur is not None:
            line += T(ctx, "brief.current", id=cur.get("id"), title=short(cur.get("title")),
                      status=status_label(ctx, cur.get("status", "todo")), fails=cur.get("fails", 0),
                      max=snap["max_fails"])
        lines.append(line)
        lines += [T(ctx, "brief.esc", text=esc_text(ctx, x)) for x in snap["esc_items"][:3]]
        if snap["stale"]:
            lines.append(T(ctx, "brief.stale", ids=", ".join("#" + s for s in snap["stale"])))
        if snap["note_only"]:
            lines.append(T(ctx, "brief.note_only", ids=", ".join("#" + s for s in snap["note_only"])))
        if snap["fp_error"]:
            lines.append(T(ctx, "brief.fp_unavailable", err=short(snap["fp_error"], 80)))
    n = snap_next(ctx, snap)
    lines.append(T(ctx, "brief.next", cmd=n["cmd"] or "—", why=short(n["why"], 160)))
    others = [w + (T(ctx, "brief.archived_tag") if os.path.exists(os.path.join(ctx.root, w, "ARCHIVED")) else "")
              for w in other_workspaces(ctx)]
    if others:
        listed = ", ".join(others[:5]) + ("，" + T(ctx, "brief.more", n=len(others)) if len(others) > 5 else "")
        lines.append(T(ctx, "brief.others", list=listed))
    lines.append(T(ctx, "brief.details", status=de_cmd(ctx, "status"), handoff=de_cmd(ctx, "handoff")))
    return lines


def brief_main(a):
    """status --brief：永远退出 0，任何错误最多一行，不把异常抛进宿主的会话钩子。"""
    utf8_stdout()
    try:
        ctx = Ctx(a.dir)
    except Exception:
        return 0
    try:
        lines = brief_lines(ctx)
    except (Exception, SystemExit) as e:
        if os.path.isfile(ctx.p(MARKER)):
            reason = e.reason if isinstance(e, Refuse) else "%s: %s" % (type(e).__name__, e)
            print(T(ctx, "brief.error", err=short(reason, 120)))
        return 0
    text = "\n".join(lines[:BRIEF_MAX_LINES])
    if len(text) > BRIEF_MAX_CHARS:
        text = text[:BRIEF_MAX_CHARS - 1] + "…"
    if text:
        print(text)
    return 0


def parse_assumptions(ci, plan):
    """决策卡假设表：编号、假设、证伪后果、状态列，以及哪些步骤在检验它。"""
    items = []
    for line in ci["assumptions"]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        aid = cells[0]
        tested = [{"step": s.get("id"), "status": s.get("status", "todo")} for s in plan["steps"]
                  if re.search(r"\b%s\b" % re.escape(aid), str(s.get("tests_assumption") or ""))]
        items.append({"id": aid, "text": cells[1] if len(cells) > 1 else "",
                      "if_false": cells[2] if len(cells) > 2 else "",
                      "status": cells[3] if len(cells) > 3 and cells[3] else "—", "tested_by": tested})
    return items


def event_line(ctx, ev):
    t, d = ev.get("type"), ""
    if t == "step":
        d = "#%s %s → %s" % (ev.get("step"), status_label(ctx, ev.get("frm")), status_label(ctx, ev.get("to")))
    elif t == "verify":
        if "results" in ev:
            d = ", ".join("#%s %s" % (r.get("step"), "ok" if r.get("ok") else "fail") for r in ev.get("results") or [])
        else:
            d = "#%s %s" % (ev.get("step"), "ok" if ev.get("ok") else "fail (exit %s)" % ev.get("exit_code"))
        if ev.get("escalated"):
            d += " ↑"
    elif t == "fail":
        d = "#%s fails=%s%s" % (ev.get("step"), ev.get("fails"), " ↑" if ev.get("escalated") else "")
    elif t in ("replan", "reopen"):
        d = "#%s" % ev.get("step") + (" waived" if ev.get("waived") else "")
    elif t == "gate":
        d = str(ev.get("gate"))
    elif t == "review":
        d = str(ev.get("verdict"))
    elif t == "archive":
        d = "%s (%s)" % (ev.get("record"), ev.get("outcome"))
    elif t == "init":
        d = str(ev.get("risk"))
    return "#%s %s %s%s" % (ev.get("seq"), ev.get("at"), t, (": " + d) if d else "")


def handoff_data(ctx, snap):
    plan, ci, fp, fp_known = snap["plan"], snap["ci"], snap["fp"], snap["fp_known"]
    steps = []
    for s in plan["steps"]:
        last = (s.get("evidence") or [{}])[-1]
        steps.append({"id": s.get("id"), "title": s.get("title"), "status": s.get("status", "todo"),
                      "evidence_kind": last.get("kind") if isinstance(last, dict) else None,
                      "freshness": evidence_state(ctx, s, fp, fp_known), "fails": s.get("fails", 0),
                      "irreversible": bool(s.get("irreversible"))})
    criteria = None
    if fp_known:
        criteria = [{"criterion": r["criterion"], "text": r["text"], "status": r["status"]}
                    for r in coverage_rows(ctx, plan, ci, fp)]
    files = {name: (ctx.rel + "/" + name).replace(os.sep, "/") for name in
             ("decision-card.md", "plan.json", "state.json", "events.jsonl", "progress.md", "retro.md",
              "independent-review.md") if os.path.exists(ctx.p(name))}
    if snap["archived"]:
        files["record"] = snap["archived"].get("record")
    return {"ok": True, "read_only": True, "workspace": ctx.rel.replace(os.sep, "/"), "title": card_title(ci),
            "verdict": ci["verdict_raw"], "stage": snap["stage"], "gates": snap["gates"],
            "risk": plan.get("risk", "standard"), "deadline": str(ci["deadline"]) if ci["deadline"] else None,
            "max_fails": snap["max_fails"], "fingerprint_error": snap["fp_error"], "steps": steps,
            "note_only_done_steps": snap["note_only"], "escalations": [esc_text(ctx, x) for x in snap["esc_items"]],
            "assumptions": parse_assumptions(ci, plan), "criteria": criteria,
            "events": [event_line(ctx, e) for e in (snap["events"] or [])[-5:]],
            "next": snap_next(ctx, snap), "files": files}


def render_handoff(ctx, h):
    none = T(ctx, "handoff.none")
    gl = {k: T(ctx, "gate." + v) for k, v in h["gates"].items()}
    out_lines = [T(ctx, "handoff.title", title=h["title"]), "",
                 T(ctx, "handoff.meta", rel=h["workspace"], verdict=h["verdict"] or none, stage=h["stage"],
                   a=gl["A"], b=gl["B"], risk=h["risk"], deadline=h["deadline"] or none)]
    if h["fingerprint_error"]:
        out_lines.append(T(ctx, "handoff.fp_unavailable", err=short(h["fingerprint_error"], 120)))
    out_lines += ["", T(ctx, "handoff.steps"), "", T(ctx, "handoff.steps_head"), "|---|---|---|---|---|---|"]
    for s in h["steps"]:
        out_lines.append("| %s |" % " | ".join(cell(x) for x in (
            s["id"], s["title"], status_label(ctx, s["status"]), s["evidence_kind"] or "—",
            T(ctx, "fresh." + s["freshness"]), "%s/%s" % (s["fails"], h["max_fails"]))))
    if h["note_only_done_steps"]:
        out_lines += ["", T(ctx, "handoff.note_only"), "", ", ".join("#" + x for x in h["note_only_done_steps"])]
    out_lines += ["", T(ctx, "handoff.esc"), ""] + (["- " + x for x in h["escalations"]] or [none])
    out_lines += ["", T(ctx, "handoff.assumptions"), "", T(ctx, "handoff.assumptions_head"), "|---|---|---|---|"]
    for x in h["assumptions"]:
        tested = ", ".join("#%s (%s)" % (t["step"], status_label(ctx, t["status"])) for t in x["tested_by"]) or "—"
        out_lines.append("| %s |" % " | ".join(cell(v) for v in (x["id"], x["text"], x["status"], tested)))
    if h["criteria"] is not None:
        out_lines += ["", T(ctx, "handoff.criteria"), "", T(ctx, "handoff.criteria_head"), "|---|---|---|"]
        for c in h["criteria"]:
            out_lines.append("| %s |" % " | ".join(cell(v) for v in (c["criterion"], c["text"], c["status"])))
    out_lines += ["", T(ctx, "handoff.events"), ""] + (["- " + e for e in h["events"]] or [none])
    n = h["next"]
    out_lines += ["", T(ctx, "handoff.next"), "", ("`%s` — " % n["cmd"] if n["cmd"] else "") + n["why"]]
    out_lines += ["", T(ctx, "handoff.files"), ""] + ["- `%s`" % p for p in h["files"].values() if p]
    return "\n".join(out_lines) + "\n"


def cmd_handoff(a, ctx):
    """只读交接摘要：证据状态由脚本从 state / events 推出，不是叙述；不写任何文件。"""
    ctx.require()
    h = handoff_data(ctx, collect_status(ctx, tolerate_fp_error=True))
    if a.json:
        out(h)
    utf8_stdout()
    print(render_handoff(ctx, h))


def light_next(ctx, plan=None, ci=None, fp=_LAZY):
    """写入命令之后的下一步：复用内存里的计划，不做一致性告警。"""
    return snap_next(ctx, collect_status(ctx, plan=plan, ci=ci, fp=fp, full=False, tolerate_fp_error=True))


RECORD_HEADERS = ("# 决策记录", "# Decision record")
SYNC_LINE = r"^- (?:知识同步|Knowledge sync)[:：].*$"
NOTE_LINE = r"^(- (?:说明|Note)[:：].*)$"
REPORT_MIN_BYTES = 50


def report_problem(ctx, report):
    if not os.path.isfile(report) or not inside(report, ctx.root) or os.path.getsize(report) < REPORT_MIN_BYTES:
        return "收尾报告不存在、位于项目外或内容不足 %d 字节：%s" % (REPORT_MIN_BYTES, report)
    return None


def archive_core(a, ctx, apply):
    """归档为决策记录；返回 (结果, 退出码)。apply=False 只预览。不删除任何文件。"""
    if os.path.exists(ctx.p("ARCHIVED")):
        return {"ok": True, "already_archived": True,
                "next": nx(ctx, ("sync", "--report", report_arg(ctx)), "next.sync")}, 0
    plan, ci = load_plan(ctx), card_info(ctx)
    outcome = OUTCOME_ALIASES.get(a.outcome, a.outcome)
    fp = fingerprint(ctx)
    docs_dir = os.path.realpath(a.docs_dir if os.path.isabs(a.docs_dir) else os.path.join(ctx.root, a.docs_dir))
    problems = []
    if not inside(docs_dir, ctx.root) or inside(docs_dir, ctx.dir):
        problems.append("--docs-dir 必须位于项目内且不在工作区里：%s" % docs_dir)
    errors, _ = card_errors(ci)
    if errors:
        problems.append("决策卡未通过检查：" + "；".join(errors))
    problems += retro_problems(ctx)
    review = plan.get("review") or {}
    if outcome == "完成":
        problems += review_problems(ctx, plan, fp)
        stale = [(sid_key(s.get("id")), stale_verified_step(ctx, s, fp)) for s in plan["steps"]]
        stale = [(sid, reason) for sid, reason in stale if reason]
        if stale:
            problems.append("文件或命令证据过期：%s" % stale)
        notdone = [sid_key(s.get("id")) for s in plan["steps"] if s.get("status") != "done"]
        if notdone:
            problems.append("还有未完成的步骤 %s；若是止损或放弃，用 --outcome 止损 / 放弃" % notdone)
    slug = re.sub(r'[\s/\\:*?"<>|]+', "-", card_title(ci)).strip("-.") or "decision"
    target = os.path.join(docs_dir, "%s-%s.md" % (dt.date.today().isoformat(), slug))
    if os.path.exists(target):
        problems.append("%s 已存在，不覆盖" % os.path.relpath(target, ctx.root))
    preview = {"ok": not problems, "dry_run": not apply, "outcome": outcome,
               "would_write": os.path.relpath(target, ctx.root), "problems": problems}
    if problems:
        preview["next"] = nx(ctx, None, "next.fix_problems")
        return preview, (3 if apply else 1)
    if not apply:
        preview["next"] = nx(ctx, invocation_parts() + ["--apply"], "next.apply", needs_user=True)
        return preview, 0
    L = LABELS[ctx.lang()]
    rows = list(L["table"])
    for s in plan["steps"]:
        ev = s["evidence"][-1] if s.get("evidence") else {}
        k = ev.get("kind")
        desc = (L["cmd_ev"] % (ev.get("cmd"), ev.get("exit_code"), ev.get("fingerprint")) if k == "command"
                else L["art_ev"] % (ev.get("path"), ev.get("sha")) if k == "artifact"
                else L["note_ev"] % ev.get("text") if k == "note" else "")
        rows.append("| %s |" % " | ".join(cell(x) for x in (s.get("id"), s.get("title"),
                                                           L["status"].get(s.get("status", "todo")), k or "", desc)))
    with open(ctx.p("retro.md"), encoding="utf-8") as f:
        retro = f.read()
    rep = review.get("independent_report") if isinstance(review.get("independent_report"), dict) else None
    body = "\n".join([
        L["title"] % card_title(ci), "",
        L["outcome"] % L["outcomes"][outcome],
        L["date"] % dt.date.today().isoformat(),
        L["sync_pending"],
        L["review"] % (review.get("verdict") or L["none"])]
        + ([L["review_report"] % (rep.get("path"), rep.get("sha"))] if rep else []) + [
        L["note"], "",
        L["card"], "", strip_h1(ci["text"]).replace("\n## ", "\n### "), "",
        L["exec"], "", "\n".join(rows), "",
        L["retro"], "", strip_h1(retro).replace("\n## ", "\n### "), ""])
    os.makedirs(docs_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(body)
    rel = os.path.relpath(target, ctx.root).replace(os.sep, "/")
    with open(ctx.p("ARCHIVED"), "w", encoding="utf-8") as f:
        json.dump({"record": rel, "at": now(), "outcome": outcome, "synced": False}, f, ensure_ascii=False)
    commit(ctx, plan, "archive", "归档为决策记录 %s（%s）" % (rel, outcome), record=rel, outcome=outcome)
    return {"ok": True, "archived_to": rel, "outcome": outcome,
            "next": nx(ctx, ("sync", "--report", report_arg(ctx)), "next.sync")}, 0


def cmd_archive(a, ctx):
    ctx.require()
    out(*archive_core(a, ctx, a.apply))


def load_marker(ctx):
    ctx.require()
    if not os.path.exists(ctx.p("ARCHIVED")):
        raise Refuse("尚未归档，先运行 archive", 2)
    try:
        with open(ctx.p("ARCHIVED"), encoding="utf-8") as f:
            m = json.load(f)
    except ValueError:
        raise Refuse("ARCHIVED 标记已损坏", 3)
    rec = m.get("record") if isinstance(m, dict) else None
    ok = isinstance(rec, str) and rec and not os.path.isabs(rec)
    path = os.path.realpath(os.path.join(ctx.root, rec)) if ok else None
    if not ok or not inside(path, ctx.root) or inside(path, ctx.dir) or not os.path.isfile(path) \
            or not path.endswith(".md"):
        raise Refuse("ARCHIVED 记录的决策记录路径不可信或不存在：%r" % rec, 3)
    with open(path, encoding="utf-8") as f:
        if not f.read(200).startswith(RECORD_HEADERS):
            raise Refuse("ARCHIVED 指向的文件不是 de.py 生成的决策记录：%s" % rec, 3)
    return m, path


def sync_core(a, ctx):
    """必须在本次调用真实运行 closing-out 静态审计；外部 JSON 不构成信任依据。返回 (结果, 退出码)。"""
    m, record = load_marker(ctx)
    trusted = os.path.realpath(os.path.join(os.path.dirname(SKILL_DIR), "closing-out", "scripts", "audit.py"))
    if not os.path.isfile(trusted):
        raise Refuse("没有安装 closing-out 的 audit.py，无法可信同步；请先安装配套 Skill", 3)
    audit_path = ctx.p("closeout-audit.json")
    if a.audit_json and os.path.realpath(a.audit_json) != os.path.realpath(audit_path):
        raise Refuse("--audit-json 仅允许指向工作区 closeout-audit.json；此参数是本次审计的输出位置，不再读取第三方报告", 2)
    problem = report_problem(ctx, a.report)
    if problem:
        return {"ok": False, "problems": [problem], "next": nx(ctx, None, "next.fix_problems")}, 3
    try:
        proc = subprocess.run([sys.executable, trusted, "--root", ctx.root], cwd=ctx.root,
                              capture_output=True, text=True, encoding="utf-8", timeout=180,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        audit = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        raise Refuse("本次真实审计未能完成：%s" % e, 3)
    summ = audit.get("summary", {})
    fp = fingerprint(ctx)
    problems = []
    if proc.returncode != 0 or not audit.get("ok"):
        problems.append("本次审计未通过（退出码 %d、error %s）" % (proc.returncode, summ.get("error")))
    if audit.get("truncated") is not False or audit.get("complete") is not True:
        problems.append("本次审计输出被截断或不完整")
    if audit.get("evidence_level") != "static":
        problems.append("审计证据层级异常")
    if audit.get("fingerprint") != fp:
        problems.append("本次审计与当前代码指纹不匹配或无法确认")
    if os.path.realpath(audit.get("inventory", {}).get("root", "")) != ctx.root:
        problems.append("本次审计目标不是当前项目根目录")
    if problems:
        return {"ok": False, "problems": problems, "audit_summary": summ, "next": nx(ctx, None, "next.fix_problems")}, 3
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    with open(a.report, encoding="utf-8") as f:
        report = f.read()
    with open(record, encoding="utf-8") as f:
        body = f.read()
    L = LABELS[ctx.lang()]
    stamp = L["sync"] + L["sync_done"] % (dt.date.today().isoformat(), summ.get("warn", "?"))
    body = re.sub(SYNC_LINE, lambda _: stamp, body, count=1, flags=re.M)
    body += "\n%s\n\n" % L["sync_report"] + strip_h1(report).replace("\n## ", "\n### ") + "\n"
    with open(record, "w", encoding="utf-8") as f:
        f.write(body)
    m.update(synced=True, synced_at=now(), audit_fingerprint=audit["fingerprint"])
    with open(ctx.p("ARCHIVED"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    commit(ctx, None, "sync", "本次真实静态审计完成，知识同步报告已并入 %s" % m["record"])
    return {"ok": True, "record": m["record"], "audit_summary": summ,
            "next": nx(ctx, ("purge",), "next.purge")}, 0


def cmd_sync(a, ctx):
    out(*sync_core(a, ctx))


def cmd_closeout(a, ctx):
    """5A 归档 + 5B 知识同步一步完成：不带 --apply 只预览；带 --apply 写入决策记录并现场重跑审计。"""
    ctx.require()
    problem = report_problem(ctx, a.report)
    if not a.apply:
        res, code = archive_core(a, ctx, False)
        if problem:
            res = dict(res, ok=False, problems=res.get("problems", []) + [problem + "；先按 closing-out 完整档写好报告"])
            code = code or 1
        res.update(closeout_preview=True, report=a.report)
        res["next"] = nx(ctx, invocation_parts() + ["--apply"], "next.apply", needs_user=True) if code == 0 \
            else nx(ctx, None, "next.fix_problems")
        out(res, code)
    if problem:
        out({"ok": False, "problems": [problem], "next": nx(ctx, None, "next.fix_problems")}, 3)
    res, code = archive_core(a, ctx, True)
    if code != 0:
        out(res, code)
    try:
        sres, scode = sync_core(a, ctx)
    except Refuse as r:
        sres, scode = {"ok": False, "problems": [r.reason]}, r.code
    out({"ok": scode == 0, "archive": res, "sync": sres,
         "next": sres.get("next") if scode == 0
         else nx(ctx, ("sync", "--report", a.report), "next.sync")}, scode)


def cmd_purge(a, ctx):
    m, record = load_marker(ctx)
    if not m.get("synced"):
        raise Refuse("知识同步未完成（sync），不能删除工作区")
    files, unknown = [], []
    for d, dirs, fs in os.walk(ctx.dir):
        unknown += [os.path.relpath(os.path.join(d, x), ctx.dir) + "/" for x in dirs]
        dirs[:] = []
        for x in fs:
            full, rel = os.path.join(d, x), os.path.relpath(os.path.join(d, x), ctx.dir)
            if os.path.islink(full) or rel not in WORKSPACE_FILES:
                unknown.append(rel)
            else:
                with open(full, "rb") as f:
                    files.append((rel, sha(f.read(), 16)))
    if unknown:
        raise Refuse("工作区里有不由 de.py 管理的文件或目录，拒绝删除：%s" % unknown, 3, unknown=unknown)
    if not ctx.git:
        raise Refuse("非 git 项目无法保证删除后可恢复；请用户确认后自行删除：%s" % ctx.dir, 3)
    rels = [(ctx.rel + "/" + f).replace(os.sep, "/") for f, _ in files]
    _, tracked = run(["git", "ls-files", "-z", "--"] + rels, ctx.root)
    tracked = set(x.decode("utf-8", "replace") for x in tracked.split(b"\0") if x)
    _, dirty = run(["git", "status", "--porcelain=v1", "-z", "--", ctx.rel], ctx.root)
    untracked = [r for r in rels if r not in tracked]
    if untracked or dirty:
        raise Refuse("工作区有未提交的内容，删除后无法从 git 恢复。先提交：%s" % (untracked or "存在修改"), 3)
    payload = {"dir": ctx.dir, "files": sorted(files), "record": m.get("record")}
    two_step(ctx, "purge", payload, a.confirm,
             {"将删除目录": ctx.rel, "文件": [f for f, _ in sorted(files)],
              "可恢复": "这些文件均已提交，可用 git 恢复", "决策记录保留在": m.get("record")})
    lang = ctx.lang()
    shutil.rmtree(ctx.dir)
    with open(record, encoding="utf-8") as f:
        body = f.read()
    body = re.sub(NOTE_LINE, lambda mm: "%s\n%s" % (LABELS[lang]["purged"] % dt.date.today().isoformat(), mm.group(1)),
                  body, count=1, flags=re.M)
    with open(record, "w", encoding="utf-8") as f:
        f.write(body)
    out({"ok": True, "removed": ctx.rel, "record": m.get("record"),
         "next": nx(ctx, None, "next.purge_done")})


def cmd_list(a, ctx):
    items = []
    for rel in find_workspaces(ctx.root, ctx.git):
        d = os.path.join(ctx.root, rel)
        items.append({"dir": rel, "selected": os.path.realpath(d) == ctx.dir,
                      "archived": os.path.exists(os.path.join(d, "ARCHIVED"))})
    out({"ok": True, "workspaces": items,
         "note": "同一仓库并行推进多件事时，每件事一个工作区（如 .decision-<名称>），所有命令带 --dir 或设置 DE_WORKSPACE"})


def cmd_show(a, ctx):
    ctx.require()
    plan = load_plan(ctx)
    print("# 计划表：%s（风险档位：%s）\n" % (plan.get("name", ""), plan.get("risk", "standard")))
    print("| # | 步骤 | 完成判据 | 验证方法 | 验证命令 | 依赖 | 覆盖标准 | 预计/已用(h) | 状态 | 失败 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s in plan["steps"]:
        print("| %s |" % " | ".join(cell(x) for x in (
            s.get("id"), ("[不可逆] " if s.get("irreversible") else "") + str(s.get("title", "")),
            s.get("done_when"), s.get("verify"), verify_spec(s)[1],
            ",".join(map(str, s.get("depends_on", []))), ",".join(map(str, s.get("covers", []))),
            "%s/%s" % (s.get("estimate_h", ""), s.get("spent_h", 0)),
            STATUS_ZH.get(s.get("status", "todo")), s.get("fails", 0))))
    it = [x for x in plan.get("if_then", []) if isinstance(x, dict) and x.get("if")]
    if it:
        print("\n## if-then 预案")
        for x in it:
            print("- 如果 %s，就 %s" % (x.get("if"), x.get("then")))


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def add(name, h):
        sp = sub.add_parser(name, help=h)
        sp.add_argument("--dir", help="工作区目录（默认 $DE_WORKSPACE 或 <项目根>/.decision，必须位于项目内）")
        return sp

    s = add("init", "创建工作区（已有工作区不会被覆盖）")
    s.add_argument("--name")
    s.add_argument("--risk", choices=RISKS, default="standard")
    s.add_argument("--lang", choices=LANGS, default="zh", help="模板语言（决策卡、计划、复盘、决策记录）")
    add("list", "列出本仓库所有工作区")
    s = add("check", "只校验，不改状态")
    s.add_argument("target", choices=["card", "plan"])
    s = add("gate", "闸门 A（决策卡）/ B（计划）/ AB（标准档一次确认两者）的两步确认")
    s.add_argument("which", choices=["A", "B", "AB"])
    s.add_argument("--confirm")
    s = add("status", "当前阶段、闸门、升级与证据状态")
    s.add_argument("--brief", action="store_true",
                   help="纯文本简要状态（≤15 行），给会话开始钩子用；没有工作区时不输出，永远退出 0")
    s = add("handoff", "只读交接摘要（Markdown；--json 输出 JSON），不写任何文件")
    s.add_argument("--json", action="store_true")
    add("preflight", "只读环境/Git/命令副作用预检")
    add("coverage", "只读验收条件与证据覆盖映射")
    s = add("step", "更新步骤状态（受状态机、闸门与证据规则约束）")
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=[x for x in STATUSES if x != "needs_replan"])
    s.add_argument("--evidence", help="文字证据（仅标准档，记为未验证）")
    s.add_argument("--artifact", help="证据文件路径（项目内）")
    s.add_argument("--hours", type=float, help="本次投入的小时数（累计到 spent_h）")
    s.add_argument("--note")
    s.add_argument("--confirm", help="不可逆步骤开始时的确认 token")
    s.add_argument("--timeout", type=int, default=600, help="验证命令超时秒数（默认 600）")
    s = add("verify", "由脚本执行验证命令（verify_argv / verify_cmd）并记录结果")
    s.add_argument("id", nargs="?")
    s.add_argument("--all", action="store_true")
    s.add_argument("--timeout", type=int, default=600)
    s = add("fail", "记录一次验证失败；达到上限自动进入待重新规划")
    s.add_argument("id")
    s.add_argument("--note", required=True)
    s.add_argument("--hours", type=float)
    s = add("replan", "解除待重新规划：要求步骤已修改，或记录豁免")
    s.add_argument("id")
    s.add_argument("--note", required=True)
    s.add_argument("--waive", help="不修改步骤而继续的理由（需两步确认）")
    s.add_argument("--confirm")
    s = add("reopen", "重新打开已完成的步骤（旧证据归档，审查结论作废）")
    s.add_argument("id")
    s.add_argument("--reason", required=True)
    s = add("review", "记录交付审查结论（两步确认）")
    s.add_argument("--verdict", required=True, choices=["pass", "fix", "fail"])
    s.add_argument("--blocker", action="append", default=[])
    s.add_argument("--independent-report", action="store_true",
                   help="关联工作区里的 independent-review.md（记录哈希；之后被改动审查结论失效）")
    s.add_argument("--confirm")
    s = add("archive", "归档为决策记录（默认只预览；不删除任何文件）")
    s.add_argument("--outcome", choices=OUTCOMES + list(OUTCOME_ALIASES), default="完成")
    s.add_argument("--docs-dir", default=os.path.join("docs", "decisions"))
    s.add_argument("--apply", action="store_true")
    s = add("sync", "登记 closing-out 的审计与报告，完成知识同步")
    s.add_argument("--audit-json", help="本次真实审计输出文件，仅允许使用工作区 closeout-audit.json")
    s.add_argument("--report", required=True)
    s = add("closeout", "archive + sync 一步完成（默认只预览；--apply 执行）")
    s.add_argument("--report", required=True)
    s.add_argument("--outcome", choices=OUTCOMES + list(OUTCOME_ALIASES), default="完成")
    s.add_argument("--docs-dir", default=os.path.join("docs", "decisions"))
    s.add_argument("--apply", action="store_true")
    s.set_defaults(audit_json=None)
    s = add("purge", "删除已归档且已同步的工作区（两步确认；要求已提交到 git）")
    s.add_argument("--confirm")
    add("show", "把计划渲染成 Markdown 表格")

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        sys.exit(2)
    if a.cmd == "status" and a.brief:
        sys.exit(brief_main(a))         # 在构造 Ctx 之前分流：钩子里永远不报错
    global _CTX
    try:
        ctx = _CTX = Ctx(a.dir)
        {"init": cmd_init, "check": cmd_check, "gate": cmd_gate, "status": cmd_status, "step": cmd_step,
         "verify": cmd_verify, "preflight": cmd_preflight, "coverage": cmd_coverage, "fail": cmd_fail, "replan": cmd_replan, "reopen": cmd_reopen,
         "review": cmd_review, "archive": cmd_archive, "sync": cmd_sync, "purge": cmd_purge,
         "closeout": cmd_closeout, "list": cmd_list, "show": cmd_show, "handoff": cmd_handoff}[a.cmd](a, ctx)
    except Refuse as r:
        print(("需要确认：" if r.extra.get("needs_confirmation") else "拒绝：") + r.reason, file=sys.stderr)
        extra = dict(r.extra)
        extra.setdefault("next", fallback_next(_CTX))
        out(dict({"ok": False, "refused": r.code == 3, "reason": r.reason}, **extra), r.code)


if __name__ == "__main__":
    main()
