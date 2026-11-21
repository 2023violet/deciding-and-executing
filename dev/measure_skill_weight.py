#!/usr/bin/env python3
"""测量技能的"阅读负担"：Agent 走一次标准流程要读多少字，以及 SKILL.md 里术语堆了多少。

v6 减重前后各跑一次做对比（docs/proposals/2026-11-19-skills-v6-slimming.md 的 S0 与复测）。
只用标准库；不修改任何文件。
用法: python dev/measure_skill_weight.py [--json]
"""
import argparse
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DE = os.path.join(ROOT, "skills", "deciding-and-executing")
CO = os.path.join(ROOT, "skills", "closing-out")

# 一次标准档流程（从定方向到收尾）Agent 通常会读的文件；文件改名或合并时在这里同步。
# v6 之前是 SKILL.md + 五份阶段文档 + verification-strategy.md（共 7 个，见 dev/eval-runs/v6-baseline/weight.json）
STANDARD_FLOW = ["SKILL.md", "references/direction.md", "references/plan-and-execute.md",
                 "references/review-and-close.md"]
FIRST_USE_EXTRA = ["references/worked-example.md"]
JARGON = ["闸门", "证据链", "证据", "指纹", "两步确认", "门禁", "基线", "哈希", "token", "preview"]


def chars(path):
    with open(path, encoding="utf-8") as f:
        return len(f.read())


def body(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return text.split("---", 2)[2] if text.startswith("---") else text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    flow = [p for p in STANDARD_FLOW if os.path.exists(os.path.join(DE, p))]
    report = {
        "skill_md_chars": {"deciding-and-executing": chars(os.path.join(DE, "SKILL.md")),
                           "closing-out": chars(os.path.join(CO, "SKILL.md"))},
        "skill_md_lines": {"deciding-and-executing": len(body(os.path.join(DE, "SKILL.md")).splitlines()),
                           "closing-out": len(body(os.path.join(CO, "SKILL.md")).splitlines())},
        "standard_flow_files": flow,
        "standard_flow_chars": sum(chars(os.path.join(DE, p)) for p in flow),
        "first_use_extra_chars": sum(chars(os.path.join(DE, p)) for p in FIRST_USE_EXTRA
                                     if os.path.exists(os.path.join(DE, p))),
        "references_chars": {os.path.basename(p): chars(p)
                             for p in sorted(glob.glob(os.path.join(DE, "references", "*.md")))},
        "jargon_in_skill_md": {},
    }
    text = body(os.path.join(DE, "SKILL.md"))
    for w in JARGON:
        # "证据链" 单独计数，"证据" 不重复统计其中的部分
        n = len(re.findall(re.escape(w), text)) - (len(re.findall("证据链", text)) if w == "证据" else 0)
        report["jargon_in_skill_md"][w] = n
    report["jargon_total"] = sum(report["jargon_in_skill_md"].values())
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("SKILL.md 字符数:", report["skill_md_chars"], " 正文行数:", report["skill_md_lines"])
    print("标准流程读入字符数: %d（%d 个文件）；第一次使用另加 %d"
          % (report["standard_flow_chars"], len(flow), report["first_use_extra_chars"]))
    print("SKILL.md 术语出现次数: %d %s" % (report["jargon_total"], report["jargon_in_skill_md"]))


if __name__ == "__main__":
    main()
