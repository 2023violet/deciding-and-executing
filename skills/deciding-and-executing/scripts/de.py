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
VERSION = "4.1.0"
MARKER = ".de-workspace"
WORKSPACE_FILES = {MARKER, "decision-card.md", "plan.json", "state.json", "events.jsonl", "progress.md",
                   "retro.md", "ARCHIVED", "closeout-audit.json", "closeout-report.md"}
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


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


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

    def p(self, name):
        return os.path.join(self.dir, name)

    def require(self):
        if not os.path.isfile(self.p(MARKER)):
            raise Refuse("%s 不是由 de.py init 创建的工作区（缺少 %s）" % (self.dir, MARKER), 2)

    def lang(self):
        try:
            with open(self.p(MARKER), encoding="utf-8") as f:
                lang = json.load(f).get("lang", "zh")
        except (OSError, ValueError, AttributeError):
            lang = "zh"
        return lang if lang in LANGS else "zh"


def find_workspaces(root, git):
    """本仓库里所有带标记的工作区（相对路径）。跳过规则与 audit.py 相同，保证两边指纹一致。"""
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
                     "escalation", "escalation_history", "waivers")
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


def state_warnings(ctx, plan):
    """state.json 是否由 de.py 最后一次写入；plan.json 里是否混入了会被忽略的运行时字段。"""
    w, meta = [], plan.get("_meta") or {}
    if meta.get("legacy"):
        w.append("工作区来自 4.2 之前的版本：运行时状态仍在 plan.json，下一次写入命令会自动迁移到 state.json")
    if meta.get("ignored"):
        w.append("plan.json 里的运行时字段由脚本维护（实际值在 state.json），以下内容与实际状态不同，已忽略：%s"
                 % "、".join(meta["ignored"][:10]))
    if os.path.exists(ctx.p("state.json")):
        st = read_json(ctx.p("state.json"), "state.json")
        ev = next((e for e in read_events(ctx) if e.get("seq") == st.get("last_event")), {})
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
    return sha({"verdict": ci["verdict"], "sec": approved}, 16)


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


def require_gate_b(plan, ci):
    gs = gate_state(plan, ci)
    if gs["B"] != "valid":
        raise Refuse("计划未通过闸门 B，或通过后决策卡/计划结构已改变（A=%s，B=%s）。先运行 gate A / gate B 重新确认"
                     % (gs["A"], gs["B"]), gates=gs)


def two_step(kind, payload, confirm, preview):
    tok = token_for(kind, payload)
    if confirm is None:
        raise Refuse("向用户展示 preview，用户明确同意后带 --confirm %s 重新运行" % tok,
                     3, needs_confirmation=True, token=tok, preview=preview)
    if confirm != tok:
        raise Refuse("确认 token 不匹配：内容已变化或 token 有误。重新运行不带 --confirm 的命令查看最新内容", 3,
                     needs_confirmation=True)
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


# ---------------------------------------------------------------- R2：只读预检与验收覆盖
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


def cmd_coverage(a, ctx):
    """只给证据覆盖候选，不把步骤自报 covers 当成成功标准已验证。"""
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    fp = fingerprint(ctx)
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
            linked.append({"step": step.get("id"), "state": state,
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
    out({"ok": True, "read_only": True, "fingerprint": fp, "criteria": items,
         "all_ready_for_review": bool(items) and all(x["status"] == "READY_FOR_INDEPENDENT_REVIEW" for x in items),
         "limits": ["covers 由 Agent 编写，不证明测试与真实需求存在语义对应",
                    "命令 PASS 仅证明该命令成功退出；artifact 完整不证明内容属实",
                    "即便全部 READY_FOR_INDEPENDENT_REVIEW，也不等于用户验收通过"]})


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
         "next": "填写 decision-card.md，然后 check card → gate A"})


def cmd_check(a, ctx):
    ctx.require()
    ci = card_info(ctx)
    if a.target == "card":
        errors, warnings = card_errors(ci)
        out({"ok": not errors, "errors": errors, "warnings": warnings,
             "verdict": ci["verdict"], "assumptions": ci["assumptions"]}, 0 if not errors else 1)
    plan = load_plan(ctx)
    errors, warnings = plan_errors(plan, ci)
    out({"ok": not errors, "errors": errors, "warnings": warnings, "step_count": len(plan["steps"]),
         "risk": plan.get("risk", "standard")}, 0 if not errors else 1)


def gate_a_preview(ci, warnings):
    return {"结论": ci["verdict_raw"], "成功标准": ci["criteria"],
            "止损": {"触发状态": ci["trigger"], "期限": str(ci["deadline"]), "动作": ci["action"]},
            "warnings": warnings}


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
            out({"ok": False, "gate": "A", "errors": errors, "warnings": warnings_a}, 1)
        ha = gate_a_hash(ci)
    if a.which == "A":
        two_step("gate-A", ha, a.confirm, gate_a_preview(ci, warnings_a))
        gates["A"] = {"hash": ha, "at": now(), "confirmed_via": "token"}
        gates.pop("B", None)
        commit(ctx, plan, "gate", "闸门 A 通过（决策卡已确认）", gate="A", hash=ha)
        out({"ok": True, "gate": "A", "next": "制定计划，然后 check plan → gate B"})
    if a.which == "B":
        gs = gate_state(plan, ci)
        if gs["A"] != "valid":
            raise Refuse("闸门 A 未通过或决策卡核心内容已改变，先运行 gate A", gates=gs)
        ha = gates["A"]["hash"]
    elif plan.get("risk") == "high":
        raise Refuse("高风险档必须分别确认 gate A 与 gate B：方向和计划各自需要用户看清后同意", 2)
    errors, warnings_b = plan_errors(plan, ci)
    if errors:
        out({"ok": False, "gate": "B", "errors": errors, "warnings": warnings_b}, 1)
    hb = plan_hash(plan)
    if a.which == "B":
        two_step("gate-B", hb, a.confirm, gate_b_preview(plan, warnings_b))
        msg = "闸门 B 通过（计划已确认）"
    else:
        two_step("gate-AB", {"a": ha, "b": hb}, a.confirm,
                 {"决策卡": gate_a_preview(ci, warnings_a), "计划": gate_b_preview(plan, warnings_b),
                  "说明": "一次确认同时通过闸门 A（方向）与闸门 B（计划），并同意执行计划里的验证命令"})
        gates["A"] = {"hash": ha, "at": now(), "confirmed_via": "token"}
        msg = "闸门 A、B 一次确认通过（决策卡与计划）"
    gates["B"] = {"hash": hb, "a_hash": ha, "at": now(), "confirmed_via": "token"}
    commit(ctx, plan, "gate", msg, gate=a.which, hash=hb)
    out({"ok": True, "gate": a.which, "first_step": plan.get("first_step")})


def cmd_status(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    steps = plan["steps"]
    fp = fingerprint(ctx)
    gs = gate_state(plan, ci)
    counts = {k: sum(1 for s in steps if s.get("status", "todo") == k) for k in STATUSES}
    warnings, escalations = state_warnings(ctx, plan), []
    seq = last_event_seq(ctx)
    if plan.get("last_event", 0) < seq:
        warnings.append("plan.json 落后于事件日志（最后事件 #%d，计划记录 #%d）：上次写入可能中断，请检查 events.jsonl"
                        % (seq, plan.get("last_event", 0)))
    for s in steps:
        sid = sid_key(s.get("id"))
        if s.get("status") == "needs_replan":
            escalations.append("步骤 %s 已失败 %d 次（上限 %d），待重新规划：修改步骤后 replan，再重新通过 gate B"
                               % (sid, s.get("fails", 0), ci["max_fails"])
                               + ("；它验证的是假设 %s，先回到定方向重审" % s["tests_assumption"]
                                  if s.get("tests_assumption") else ""))
        est, spent = s.get("estimate_h"), s.get("spent_h", 0)
        if isinstance(est, (int, float)) and est > 0 and spent > 2 * est and s.get("status") != "done":
            escalations.append("步骤 %s 已投入 %.1fh，超过预计 %.1fh 的一倍：一级升级，回到计划层" % (sid, spent, est))
    if isinstance(ci["deadline"], dt.date) and dt.date.today() >= ci["deadline"] and counts["done"] < len(steps):
        escalations.append("已到止损期限 %s（触发状态：%s）：二级升级，对照决策卡判断是否执行动作「%s」"
                           % (ci["deadline"], ci["trigger"], ci["action"]))
    stale = [sid_key(s.get("id")) for s in steps if s.get("status") == "done"
             and stale_verified_step(ctx, s, fp)]
    note_only = [sid_key(s.get("id")) for s in steps if s.get("status") == "done"
                 and s.get("evidence") and all(e.get("kind") == "note" for e in s["evidence"])]
    review = plan.get("review") or {}
    review_valid = review.get("verdict") == "pass" and review.get("plan_hash") == plan_hash(plan) \
        and (fp is None or review.get("fingerprint") == fp)
    if os.path.exists(ctx.p("ARCHIVED")):
        try:
            with open(ctx.p("ARCHIVED"), encoding="utf-8") as f:
                synced = json.load(f).get("synced")
        except (ValueError, AttributeError):
            synced = False
            warnings.append("ARCHIVED 标记已损坏")
        stage = "ready-to-purge" if synced else "archived"
    elif gs["A"] != "valid":
        stage = "direction"
    elif gs["B"] != "valid":
        stage = "plan"
    elif counts["needs_replan"]:
        stage = "replan"
    elif counts["done"] < len(steps):
        stage = "execute"
    elif not review_valid:
        stage = "review"
    else:
        stage = "closeout"
    current = next((s for s in steps if s.get("status") == "in_progress"), None) \
        or next((s for s in steps if s.get("status") in ("todo", "implemented")), None)
    if fp is None:
        warnings.append("非 git 项目：无法判断证据是否对应当前代码")
    out({"stage": stage, "gates": gs, "risk": plan.get("risk", "standard"),
         "current_step": {k: current.get(k) for k in ("id", "title", "done_when", "verify", "verify_cmd", "verify_argv", "status")}
         if current else None,
         "counts": counts, "total": len(steps),
         "unverified_steps": [sid_key(s.get("id")) for s in steps if s.get("status") == "implemented"],
         "stale_evidence_steps": stale, "note_only_done_steps": note_only,
         "review": {"verdict": review.get("verdict"), "valid_for_current_code": review_valid} if review else None,
         "escalations": escalations, "warnings": warnings, "fingerprint": fp,
         "kill_deadline": str(ci["deadline"]) if ci["deadline"] else None,
         "other_workspaces": [w for w in find_workspaces(ctx.root, ctx.git)
                              if os.path.realpath(os.path.join(ctx.root, w)) != ctx.dir]})


def cmd_step(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    s = find_step(plan, a.id)
    old, new = s.get("status", "todo"), a.status
    if old == "needs_replan":
        raise Refuse("步骤 %s 已触发升级，待重新规划：先修改步骤并 replan，或用 replan --waive 记录豁免" % s.get("id"))
    if old == "done":
        raise Refuse("步骤 %s 已完成；如需重做，用 reopen 记录原因（旧证据会归档）" % s.get("id"))
    if new not in TRANSITIONS[old]:
        raise Refuse("不允许的状态转换：%s → %s。允许：%s" % (old, new, ", ".join(sorted(TRANSITIONS[old])) or "无"), 2)
    require_gate_b(plan, ci)
    if new == "in_progress":
        pending = [d for d in s.get("depends_on", []) if find_step(plan, d).get("status") != "done"]
        if pending:
            raise Refuse("步骤 %s 依赖的步骤 %s 尚未完成" % (s.get("id"), pending))
        if s.get("irreversible") and old == "todo":
            two_step("irreversible", {"step": struct_of(s), "fp": fingerprint(ctx)}, a.confirm,
                     {"步骤": s.get("title"), "警告": "这是不可逆操作，开始前需要用户确认"})
        s.setdefault("started_at", now())
    if a.hours:
        s["spent_h"] = round(float(s.get("spent_h", 0)) + a.hours, 2)
    if new == "done":
        fp = fingerprint(ctx)
        if has_verify(s):
            if not fresh_command_pass(s, fp):
                ev = run_verify(ctx, s, a.timeout)
                if not ev["ok"]:
                    commit(ctx, plan, "verify", "步骤 #%s 验证未通过（退出码 %s）" % (s.get("id"), ev["exit_code"]),
                           step=s.get("id"), ok=False, exit_code=ev["exit_code"])
                    raise Refuse("验证命令未通过（退出码 %s）：%s。未标记完成；如属一次失败，运行 fail 记录"
                                 % (ev["exit_code"], ev.get("note") or ev["output_tail"][-300:]))
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
                raise Refuse("高风险计划不接受纯文字证据：给步骤加验证命令（verify_argv / verify_cmd），或用 --artifact 指向证据文件")
            s.setdefault("evidence", []).append({"kind": "note", "text": a.evidence.strip(), "at": now(),
                                                 "fingerprint": fp, "verified": False})
        else:
            raise Refuse("没有证据不能标记完成。可用：验证命令 verify_argv / verify_cmd（脚本执行）、--artifact 文件、"
                         "或 --evidence 文字（仅标准档，记为未验证）；尚未验证就用 implemented")
        s["finished_at"] = now()
    s["status"] = new
    commit(ctx, plan, "step", "步骤 #%s %s → %s%s" % (s.get("id"), STATUS_ZH[old], STATUS_ZH[new],
                                                     ("；" + a.note) if a.note else ""),
           step=s.get("id"), frm=old, to=new, note=a.note)
    last = s["evidence"][-1] if new == "done" and s.get("evidence") else None
    out({"ok": True, "step": s.get("id"), "from": old, "to": new,
         "evidence_kind": last.get("kind") if last else None,
         "evidence_verified": (last.get("kind") in ("command", "artifact")) if last else None})


def cmd_verify(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    if not a.all and not a.id:
        raise Refuse("给出步骤 ID 或 --all", 2)
    require_gate_b(plan, ci)
    targets = [s for s in plan["steps"] if has_verify(s)] if a.all \
        else [find_step(plan, a.id)]
    results, fp = [], fingerprint(ctx)
    for s in targets:
        ev = run_verify(ctx, s, a.timeout, fp_before=fp)
        fp = ev["fingerprint"]           # 本步结束时的指纹就是下一步开始时的指纹
        results.append({"step": s.get("id"), "ok": ev["ok"], "exit_code": ev["exit_code"],
                        "seconds": ev["seconds"], "note": ev.get("note")})
    commit(ctx, plan, "verify", "执行验证：%s" % (", ".join("#%s %s" % (r["step"], "通过" if r["ok"] else "失败")
                                                          for r in results) or "无"), results=results)
    ok = all(r["ok"] for r in results)
    out({"ok": ok, "results": results, "fingerprint": fp}, 0 if ok else 1)


def cmd_fail(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    s = find_step(plan, a.id)
    if s.get("status") in ("done", "needs_replan"):
        raise Refuse("步骤 %s 当前为 %s，不能记录失败" % (s.get("id"), STATUS_ZH[s.get("status")]))
    s["fails"] = int(s.get("fails", 0)) + 1
    if a.hours:
        s["spent_h"] = round(float(s.get("spent_h", 0)) + a.hours, 2)
    esc = s["fails"] >= ci["max_fails"]
    if esc:
        s["escalation"] = {"at": now(), "fails": s["fails"], "struct_hash": sha(struct_of(s), 16),
                           "prev_status": s.get("status", "todo")}
        s["status"] = "needs_replan"
    commit(ctx, plan, "fail", "步骤 #%s 验证失败（第 %d 次）：%s%s" % (s.get("id"), s["fails"], a.note,
                                                              "；触发一级升级，待重新规划" if esc else ""),
           step=s.get("id"), fails=s["fails"], note=a.note, escalated=esc)
    out({"ok": True, "step": s.get("id"), "fails": s["fails"], "max_fails": ci["max_fails"], "escalate": esc,
         "status": s["status"],
         "next": ("停止盲试：在 plan.json 修改此步骤（拆小、换做法、补前置步骤）后运行 replan，再重新通过 gate B"
                  + ("；它验证的是假设 %s，先回到定方向重审" % s["tests_assumption"] if s.get("tests_assumption") else ""))
         if esc else "换一个独立假设再试（见 stage-3-execute.md 的诊断法）"})


def cmd_replan(a, ctx):
    ctx.require()
    plan, ci = load_plan(ctx), card_info(ctx)
    s = find_step(plan, a.id)
    if s.get("status") != "needs_replan":
        raise Refuse("步骤 %s 不在待重新规划状态" % s.get("id"), 2)
    esc = s.get("escalation") or {}
    changed = sha(struct_of(s), 16) != esc.get("struct_hash")
    if a.waive:
        two_step("waive", {"step": struct_of(s), "fails": s.get("fails"), "reason": a.waive}, a.confirm,
                 {"步骤": s.get("title"), "失败次数": s.get("fails"), "豁免理由": a.waive,
                  "后果": "不修改计划继续尝试；再失败一次会立即再次升级"})
        s["fails"] = max(0, ci["max_fails"] - 1)
        s.setdefault("waivers", []).append({"at": now(), "reason": a.waive})
    elif not changed:
        raise Refuse("步骤 %s 的内容（标题/完成判据/验证方法/验证命令/依赖等）自升级以来没有修改。"
                     "先在 plan.json 里修改此步骤；确有理由不改，用 --waive 理由" % s.get("id"))
    else:
        s["fails"] = 0
    s["status"] = esc.get("prev_status") if esc.get("prev_status") in ("todo", "blocked") else "todo"
    s.setdefault("escalation_history", []).append(dict(esc, resolved_at=now(),
                                                       resolution="waived" if a.waive else "replanned"))
    s.pop("escalation", None)
    commit(ctx, plan, "replan", "步骤 #%s %s：%s" % (s.get("id"), "豁免继续" if a.waive else "已重新规划", a.note),
           step=s.get("id"), waived=bool(a.waive), note=a.note)
    gs = gate_state(plan, ci)
    out({"ok": True, "step": s.get("id"), "status": s["status"], "gates": gs,
         "next": "计划结构已改变，运行 gate B 重新确认" if gs["B"] != "valid" else "可以继续执行"})


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
    plan.pop("review", None)
    commit(ctx, plan, "reopen", "步骤 #%s 重新打开：%s（旧证据已归档，审查结论作废）" % (s.get("id"), a.reason),
           step=s.get("id"), reason=a.reason)
    out({"ok": True, "step": s.get("id"), "status": "todo", "review_invalidated": True})


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
    require_gate_b(plan, ci)
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
        out({"ok": False, "verdict": a.verdict, "problems": problems}, 3)
    payload = {"verdict": a.verdict, "blockers": a.blocker, "plan": plan_hash(plan), "fp": fp}
    two_step("review", payload, a.confirm,
             {"结论": a.verdict, "阻断项": a.blocker,
              "步骤证据": [{"id": s.get("id"), "最后证据类型": (s.get("evidence") or [{}])[-1].get("kind")}
                       for s in plan["steps"]]})
    plan["review"] = {"verdict": a.verdict, "blockers": a.blocker, "at": now(), "fingerprint": fp,
                      "plan_hash": plan_hash(plan), "confirmed_via": "token",
                      "note": "confirmed_via=token 表示内容经两步确认；脚本无法证明确认者是人"}
    commit(ctx, plan, "review", "交付审查结论：%s%s" % (a.verdict, "；阻断项：" + "；".join(a.blocker) if a.blocker else ""),
           verdict=a.verdict, blockers=a.blocker)
    out({"ok": True, "verdict": a.verdict,
         "next": "完成复盘（retro.md）后运行 archive" if a.verdict == "pass"
         else "把阻断项作为新步骤加入计划（会要求重新确认 gate B）"})


def cell(x):
    return str(x if x is not None else "").replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def card_title(ci):
    m = re.search(r"^#\s*(?:决策卡|decision card)[:：]\s*(.+)$", ci["text"], re.M | re.I)
    return m.group(1).strip() if m else "未命名决策"


def strip_h1(text):
    return re.sub(r"\A\s*#\s[^\n]*\n", "", text, count=1).strip()


LABELS = {
    "zh": {"title": "# 决策记录：%s", "outcome": "- 结局：%s", "date": "- 归档日期：%s", "sync_pending": "- 知识同步：待完成",
           "review": "- 审查结论：%s", "none": "无",
           "note": "- 说明：本文件是历史记录，描述当时为什么这样决定；系统现状以 README 与 docs 为准。",
           "card": "## 决策卡（归档时版本）", "exec": "## 执行摘要", "retro": "## 复盘",
           "table": ["| # | 步骤 | 状态 | 证据类型 | 证据 |", "|---|---|---|---|---|"],
           "cmd_ev": "`%s` 退出码 %s（代码 %s）", "art_ev": "%s（sha %s）", "note_ev": "%s（未验证）",
           "sync": "- 知识同步：", "sync_done": "已完成（%s；本次执行静态审计 error 0、warn %s；其他证据层级见下方报告）",
           "sync_report": "## 知识同步报告", "purged": "- 工作区：已于 %s 删除（可从 git 历史恢复）",
           "outcomes": {"完成": "完成", "止损": "止损", "放弃": "放弃"}, "status": STATUS_ZH},
    "en": {"title": "# Decision record: %s", "outcome": "- Outcome: %s", "date": "- Archived: %s",
           "sync_pending": "- Knowledge sync: pending", "review": "- Review verdict: %s", "none": "none",
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
                "next": "交给 closing-out 完整档完成知识同步，然后运行 sync"}, 0
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
        if review.get("verdict") != "pass":
            problems.append("以「完成」归档需要交付审查结论为 pass（当前：%s）" % (review.get("verdict") or "无"))
        elif review.get("plan_hash") != plan_hash(plan) or (fp is not None and review.get("fingerprint") != fp):
            problems.append("审查之后计划或代码已改变，需要重新 review")
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
        return preview, (3 if apply else 1)
    if not apply:
        preview["next"] = "向用户展示预览；同意后加 --apply 写入（不会删除任何文件）"
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
    body = "\n".join([
        L["title"] % card_title(ci), "",
        L["outcome"] % L["outcomes"][outcome],
        L["date"] % dt.date.today().isoformat(),
        L["sync_pending"],
        L["review"] % (review.get("verdict") or L["none"]),
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
            "next": "交给 closing-out 完整档：报告存为 %s/closeout-report.md，再运行 sync --report %s/closeout-report.md"
                    "（sync 会现场重跑审计）" % (ctx.rel, ctx.rel)}, 0


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
        return {"ok": False, "problems": [problem]}, 3
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
        return {"ok": False, "problems": problems, "audit_summary": summ}, 3
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
            "next": "提交所有改动（含工作区），然后运行 purge 预览删除"}, 0


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
        if code == 0:
            res["next"] = "向用户展示预览；同意后加 --apply：写入决策记录，并现场重跑审计完成知识同步"
        out(res, code)
    if problem:
        out({"ok": False, "problems": [problem]}, 3)
    res, code = archive_core(a, ctx, True)
    if code != 0:
        out(res, code)
    try:
        sres, scode = sync_core(a, ctx)
    except Refuse as r:
        sres, scode = {"ok": False, "problems": [r.reason]}, r.code
    out({"ok": scode == 0, "archive": res, "sync": sres,
         "next": sres.get("next") if scode == 0
         else "决策记录已写入；修复上面的问题后运行 sync --report %s" % a.report}, scode)


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
    two_step("purge", payload, a.confirm,
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
         "next": "提交删除；如安装了 closing-out，再审计一次"})


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
    add("status", "当前阶段、闸门、升级与证据状态")
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
    try:
        ctx = Ctx(a.dir)
        {"init": cmd_init, "check": cmd_check, "gate": cmd_gate, "status": cmd_status, "step": cmd_step,
         "verify": cmd_verify, "preflight": cmd_preflight, "coverage": cmd_coverage, "fail": cmd_fail, "replan": cmd_replan, "reopen": cmd_reopen,
         "review": cmd_review, "archive": cmd_archive, "sync": cmd_sync, "purge": cmd_purge,
         "closeout": cmd_closeout, "list": cmd_list, "show": cmd_show}[a.cmd](a, ctx)
    except Refuse as r:
        print(("需要确认：" if r.extra.get("needs_confirmation") else "拒绝：") + r.reason, file=sys.stderr)
        out(dict({"ok": False, "refused": r.code == 3, "reason": r.reason}, **r.extra), r.code)


if __name__ == "__main__":
    main()
