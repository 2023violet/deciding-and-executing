#!/usr/bin/env python3
"""validate_skill.py — 按 Agent Skills 开放规范 + Claude/Codex 的额外约束检查一个技能目录。

用法: python3 dev/validate_skill.py deciding-and-executing
输出 JSON；有 errors 时退出码 1。仅用标准库。

检查项（来源见 教程-如何制作高质量Skill.md 第 4 节）:
  - frontmatter 只含 claude.ai 上传允许的字段
  - name：1-64 字符、小写字母数字连字符、不以连字符开头结尾、无连续连字符、与目录同名、不含保留词
  - description：1-1024 字符、无尖括号
  - SKILL.md 正文 < 500 行
  - SKILL.md 中的相对链接都存在；references 里引用的文件也必须能从 SKILL.md 直接到达（一层深）
  - 超过 100 行的参考文件要有目录
  - agents/openai.yaml：short_description 25-64 字符，default_prompt 提到 $技能名
  - scripts/*.py 能执行 --help
"""
import json
import os
import re
import subprocess
import sys

ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def frontmatter(text):
    """优先用 PyYAML 做真实解析（与上传端行为一致）；没有安装时退回简易解析并给出提示。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    try:
        import yaml
        data = yaml.safe_load(m.group(1))
        if not isinstance(data, dict):
            return {"__error__": "frontmatter 不是映射"}, text[m.end():]
        return data, text[m.end():]
    except ImportError:
        pass
    except Exception as e:  # yaml.YAMLError
        return {"__error__": "YAML 解析失败：%s" % e}, text[m.end():]
    fm, top = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            k, _, v = line.partition(":")
            top = k.strip()
            fm[top] = v.strip()
        # 缩进行属于上一个顶层键（如 metadata 的子项），只需知道顶层键
    return fm, text[m.end():]


def main(skill_dir):
    errors, warnings, info = [], [], {}
    skill_dir = skill_dir.rstrip("/")
    dirname = os.path.basename(skill_dir)
    sk = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(sk):
        print(json.dumps({"ok": False, "errors": ["缺少 SKILL.md"]}, ensure_ascii=False))
        sys.exit(1)
    text = open(sk, encoding="utf-8").read()
    fm, body = frontmatter(text)
    if fm is None:
        errors.append("SKILL.md 缺少 YAML frontmatter")
        fm = {}
    if "__error__" in fm:
        errors.append(fm.pop("__error__"))
    try:
        import yaml  # noqa: F401
        info["yaml_parser"] = "PyYAML"
    except ImportError:
        info["yaml_parser"] = "简易解析（未安装 PyYAML，嵌套结构未完全校验）"
    md = fm.get("metadata")
    if md is not None and (not isinstance(md, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in md.items())):
        errors.append("metadata 必须是字符串到字符串的映射（版本号要加引号，例如 version: \"4.0.0\"）")
    for k in ("name", "description"):
        if k in fm and not isinstance(fm[k], str):
            errors.append("%s 必须是字符串" % k)
    extra = set(fm) - ALLOWED_KEYS
    if extra:
        errors.append("frontmatter 含 claude.ai 不允许的字段: %s" % ", ".join(sorted(extra)))
    name = fm.get("name", "") if isinstance(fm.get("name", ""), str) else ""
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append("name 不合规: %r" % name)
    if name != dirname:
        errors.append("name (%s) 与目录名 (%s) 不一致" % (name, dirname))
    if "claude" in name or "anthropic" in name:
        errors.append("name 含保留词")
    desc = fm.get("description", "") if isinstance(fm.get("description", ""), str) else ""
    info["description_chars"] = len(desc)
    if not 1 <= len(desc) <= 1024:
        errors.append("description 长度 %d，须在 1-1024" % len(desc))
    if "<" in desc or ">" in desc:
        errors.append("description 含尖括号")
    lines = body.count("\n")
    info["body_lines"] = lines
    if lines >= 500:
        errors.append("SKILL.md 正文 %d 行，应少于 500" % lines)

    linked = set(re.findall(r"\]\(((?:references|assets|scripts)/[^)#\s]+)\)", text))
    for l in sorted(linked):
        if not os.path.exists(os.path.join(skill_dir, l)):
            errors.append("SKILL.md 链接不存在: %s" % l)
    ref_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(ref_dir):
        for f in sorted(os.listdir(ref_dir)):
            p = os.path.join(ref_dir, f)
            rel = "references/" + f
            if rel not in linked:
                warnings.append("%s 没有从 SKILL.md 链接，模型可能永远不会读它" % rel)
            content = open(p, encoding="utf-8").read()
            n = content.count("\n")
            if n > 100 and not re.search(r"^##\s*(目录|Contents)", content, re.M):
                warnings.append("%s 有 %d 行但没有目录" % (rel, n))
            for l in re.findall(r"\]\(([^)#\s]+\.md)\)", content):
                target = os.path.normpath(os.path.join("references", l))
                if not os.path.exists(os.path.join(skill_dir, target)):
                    errors.append("%s 链接不存在: %s" % (rel, l))
                elif target not in linked:
                    errors.append("%s 引用了 %s，但 SKILL.md 没有直接链接它（超过一层深）" % (rel, target))

    oy = os.path.join(skill_dir, "agents", "openai.yaml")
    if os.path.exists(oy):
        y = open(oy, encoding="utf-8").read()
        m = re.search(r'short_description:\s*"([^"]*)"', y)
        if m and not 25 <= len(m.group(1)) <= 64:
            errors.append("openai.yaml short_description 长度 %d，须在 25-64" % len(m.group(1)))
        m = re.search(r'default_prompt:\s*"([^"]*)"', y)
        if m and ("$" + name) not in m.group(1):
            errors.append("openai.yaml default_prompt 须提到 $%s" % name)

    sd = os.path.join(skill_dir, "scripts")
    if os.path.isdir(sd):
        for f in sorted(os.listdir(sd)):
            if f.endswith(".py"):
                r = subprocess.run([sys.executable, os.path.join(sd, f), "--help"],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    errors.append("scripts/%s --help 失败: %s" % (f, r.stderr[:200]))

    print(json.dumps({"ok": not errors, "skill": name, "errors": errors,
                      "warnings": warnings, "info": info}, ensure_ascii=False, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 2)
    main(sys.argv[1])
