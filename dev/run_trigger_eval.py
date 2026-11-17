#!/usr/bin/env python3
"""触发评测：一条查询跑 N 次，统计 Claude 是否选择调用被测技能（只测 description，不需要安装技能）。

做法沿用官方 skill-creator 的 run_eval.py：在一个临时空项目里写入
.claude/commands/<技能名>-skill-<随机串>.md（description 与被测技能相同），用 claude -p 发送查询，
从 stream-json 里看 Claude 是否调用了这个唯一名字的 Skill（或 Read 了它）。
与 skill-creator 的两处差别：
  - 用读线程代替 select，Windows 上也能运行；
  - 第一个工具调用是别的技能时（例如宿主插件注入的总调度技能）再多看最多 2 个工具调用，
    遇到非 Skill / Read 的工具（开始干活）或消息结束就判定未触发。

运行环境就是本机的真实环境：全局技能与插件照常加载，它们会和被测技能抢触发，结果里会记录。

用法:
  python dev/run_trigger_eval.py skills/closing-out dev/evals/closing-out/trigger_evals.json \
      [--runs 3] [--workers 4] [--timeout 120] [--model M] [--description-file F] [--out 结果.json]
判定: should_trigger=true 的查询触发率需 >= 阈值（默认 0.5）；false 的需 < 阈值。
"""
import argparse
import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

MAX_TOOL_CALLS = 3


def read_description(skill_dir):
    with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    if not m:
        sys.exit("SKILL.md 里找不到 description")
    return m.group(1).strip()


def _reader(stream, q):
    for line in iter(stream.readline, b""):
        q.put(line)
    q.put(None)


def run_once(claude, query, name, description, timeout, model):
    """返回 (是否触发, 判定依据)。"""
    unique = "%s-skill-%s" % (name, uuid.uuid4().hex[:8])
    proj = tempfile.mkdtemp(prefix="trigger-eval-")
    try:
        cmd_dir = os.path.join(proj, ".claude", "commands")
        os.makedirs(cmd_dir)
        with open(os.path.join(cmd_dir, unique + ".md"), "w", encoding="utf-8") as f:
            f.write("---\ndescription: %s\n---\n\n# %s\n\nThis skill handles: %s\n"
                    % (json.dumps(description, ensure_ascii=False), name, description))
        args = [claude, "-p", query, "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        if model:
            args += ["--model", model]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        proc = subprocess.Popen(args, cwd=proj, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        q = queue.Queue()
        threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
        tools_seen, pending, acc = 0, None, ""
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                try:
                    line = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if line is None:
                    return False, "process-ended"
                try:
                    ev = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if ev.get("type") == "stream_event":
                    se = ev.get("event", {})
                    st = se.get("type", "")
                    if st == "content_block_start" and se.get("content_block", {}).get("type") == "tool_use":
                        tool = se["content_block"].get("name", "")
                        tools_seen += 1
                        if tool not in ("Skill", "Read"):
                            return False, "first-work-tool:" + tool
                        pending, acc = tool, ""
                    elif st == "content_block_delta" and pending:
                        acc += se.get("delta", {}).get("partial_json", "")
                        if unique in acc:
                            return True, pending
                    elif st == "content_block_stop" and pending:
                        if unique in acc:
                            return True, pending
                        if tools_seen >= MAX_TOOL_CALLS:
                            return False, "other-skill:" + acc[:80]
                        pending, acc = None, ""
                    elif st == "message_stop" and not pending and tools_seen == 0:
                        return False, "answered-directly"
                elif ev.get("type") == "result":
                    return False, "result"
            return False, "timeout"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    finally:
        shutil.rmtree(proj, ignore_errors=True)


def environment(claude, model):
    def ls(p):
        p = os.path.expanduser(p)
        return sorted(os.listdir(p)) if os.path.isdir(p) else []
    try:
        ver = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        ver = None
    plugins = []
    try:
        with open(os.path.expanduser("~/.claude/settings.json"), encoding="utf-8") as f:
            plugins = sorted(k for k, v in (json.load(f).get("enabledPlugins") or {}).items() if v)
    except (OSError, ValueError):
        pass
    return {"claude_version": ver, "model": model or "default", "global_skills": len(ls("~/.claude/skills")),
            "enabled_plugins": plugins, "platform": sys.platform}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill_dir")
    ap.add_argument("eval_set")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--model")
    ap.add_argument("--description-file", help="用这个文件的内容代替 SKILL.md 的 description（迭代描述时用）")
    ap.add_argument("--out", help="结果 JSON 写到这里")
    a = ap.parse_args()
    claude = shutil.which("claude")
    if not claude:
        sys.exit("找不到 claude CLI")
    name = os.path.basename(os.path.normpath(a.skill_dir))
    description = read_description(a.skill_dir)
    if a.description_file:
        with open(a.description_file, encoding="utf-8") as f:
            description = f.read().strip()
    with open(a.eval_set, encoding="utf-8") as f:
        cases = json.load(f)
    jobs = [(i, r) for i in range(len(cases)) for r in range(a.runs)]
    hits = {i: [] for i in range(len(cases))}
    lock = threading.Lock()
    started = time.time()

    def work(job):
        i, _ = job
        ok, why = run_once(claude, cases[i]["query"], name, description, a.timeout, a.model)
        with lock:
            hits[i].append({"triggered": ok, "why": why})
            done = sum(len(v) for v in hits.values())
            print("[%d/%d] %s %s" % (done, len(jobs), "T" if ok else "-", cases[i]["query"][:50]),
                  file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, jobs))
    results = []
    for i, c in enumerate(cases):
        n = sum(1 for h in hits[i] if h["triggered"])
        rate = n / max(1, len(hits[i]))
        passed = rate >= a.threshold if c["should_trigger"] else rate < a.threshold
        results.append({"query": c["query"], "should_trigger": c["should_trigger"], "trigger_rate": round(rate, 2),
                        "runs": hits[i], "pass": passed})
    pos = [r for r in results if r["should_trigger"]]
    neg = [r for r in results if not r["should_trigger"]]
    summary = {"passed": sum(r["pass"] for r in results), "total": len(results),
               "positives_passed": sum(r["pass"] for r in pos), "positives": len(pos),
               "negatives_passed": sum(r["pass"] for r in neg), "negatives": len(neg),
               "seconds": round(time.time() - started)}
    report = {"skill": name, "date": dt.date.today().isoformat(), "description": description,
              "runs_per_query": a.runs, "threshold": a.threshold, "environment": environment(claude, a.model),
              "summary": summary, "results": results}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(summary, ensure_ascii=False))
    for r in results:
        if not r["pass"]:
            print("FAIL rate=%.2f want=%s  %s" % (r["trigger_rate"], r["should_trigger"], r["query"]))
    sys.exit(0 if summary["passed"] == summary["total"] else 1)


if __name__ == "__main__":
    main()
