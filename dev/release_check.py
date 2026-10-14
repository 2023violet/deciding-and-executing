#!/usr/bin/env python3
"""release_check.py — 发布前一次性检查（仅标准库；有 PyYAML 时 frontmatter 校验更严格）。

检查：
  1. 每个技能通过 validate_skill.py
  2. 全量回归测试通过（与使用者 git 全局配置隔离），并记录耗时
  3. dist/*.skill 的内容与 skills/ 逐文件一致（防止发布旧包）
  4. 每个技能的 metadata.version 在 CHANGELOG.md 里有对应条目
  5. 用 closing-out 审计本仓库自身：error 0 且输出完整

用法: python3 dev/release_check.py            # 在仓库根目录运行
输出 JSON；全部通过退出码 0，否则 1。
"""
import argparse
import tempfile
import pathlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "dev", "tests"))
from helpers import ENV  # noqa: E402


def sh(args, timeout=900):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, env=ENV, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def file_hashes_dir(d):
    out = {}
    for base, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f.endswith(".pyc"):
                continue
            p = os.path.join(base, f)
            out[os.path.relpath(p, os.path.dirname(d)).replace(os.sep, "/")] = \
                hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def validate_outer(archive):
    """解压最终 ZIP，核对 Unicode 文件名、所有文件哈希与文档链接。"""
    expected = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in pathlib.Path(ROOT).rglob("*") if p.is_file()
                and "__pycache__" not in p.parts and not p.name.endswith(".pyc")}
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory(prefix="skill-release-") as td:
        rootname = "deciding-and-executing-v4.1.0"
        actual = {}
        for obj in z.infolist():
            name = obj.filename
            pp = pathlib.PurePosixPath(name)
            if pp.is_absolute() or ".." in pp.parts or not name.startswith(rootname + "/"):
                return {"ok": False, "reason": "ZIP 路径越界或根目录不正确", "file": name}
            if obj.is_dir():
                continue
            if any(ord(c) > 127 for c in name) and not (obj.flag_bits & 0x800):
                return {"ok": False, "reason": "Unicode 文件名缺少 ZIP UTF-8 标记", "file": name}
            actual[pp.relative_to(rootname).as_posix()] = hashlib.sha256(z.read(name)).hexdigest()
        if actual != expected:
            return {"ok": False, "reason": "外层 ZIP 与源码不一致", "paths": sorted(set(actual.items()) ^ set(expected.items()))[:6]}
        z.extractall(td)
        base = pathlib.Path(td, rootname)
        for required in ["docs/教程-如何制作高质量Skill.md", "docs/内审报告-v4.0.0.md",
                         "docs/v4.0.1-独立验收记录.md", "docs/Skill-愿景与演进路线.md"]:
            if not (base / required).is_file():
                return {"ok": False, "reason": "Unicode 路径解压后缺失", "file": required}
        run = subprocess.run([sys.executable, str(base / "skills/closing-out/scripts/audit.py"),
                              "--root", str(base), "--exclude", "dev/eval-runs/*"],
                             capture_output=True, text=True, timeout=180)
        try:
            result = json.loads(run.stdout)
        except ValueError:
            return {"ok": False, "reason": "解压后审计未返回合法 JSON", "detail": run.stderr[:200]}
        return {"ok": run.returncode == 0 and result["complete"] and result["summary"]["error"] == 0,
                "files": len(actual), "static_audit": result["summary"],
                "dead_links": [x for x in result["findings"] if x["check"] == "dead-links"][:10]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outer-zip", default=os.path.join(os.path.dirname(ROOT), "deciding-and-executing-v4.1.0.zip"),
                    help="最终交付 ZIP；必查，默认使用仓库同级 deciding-and-executing-v4.1.0.zip")
    a = ap.parse_args()
    results, ok = [], True
    skills = sorted(x for x in os.listdir(os.path.join(ROOT, "skills"))
                    if os.path.isfile(os.path.join(ROOT, "skills", x, "SKILL.md")))
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    for s in skills:
        code, o, _ = sh([sys.executable, "dev/validate_skill.py", "skills/" + s])
        results.append({"check": "validate:" + s, "ok": code == 0, "detail": json.loads(o).get("errors")})
        m = re.search(r'version:\s*"?([\w.]+)"?', open(os.path.join(ROOT, "skills", s, "SKILL.md"), encoding="utf-8").read())
        ver = m.group(1) if m else None
        has = bool(ver) and re.search(r"%s\s+%s|%s.*%s" % (re.escape(s), re.escape(ver), re.escape(s), re.escape(ver)), changelog)
        results.append({"check": "changelog:" + s, "ok": bool(has), "detail": "metadata.version=%s" % ver})
        pkg = os.path.join(ROOT, "dist", s + ".skill")
        if not os.path.exists(pkg):
            results.append({"check": "dist:" + s, "ok": False, "detail": "缺少 %s" % pkg})
        else:
            with zipfile.ZipFile(pkg) as z:
                packed = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith("/")}
            src = file_hashes_dir(os.path.join(ROOT, "skills", s))
            diff = sorted(set(packed.items()) ^ set(src.items()))
            results.append({"check": "dist:" + s, "ok": not diff,
                            "detail": "一致" if not diff else "不一致：%s" % sorted({k for k, _ in diff})[:10]})
    t = time.time()
    code, o, e = sh([sys.executable, "-m", "unittest", "discover", "-s", "dev/tests"])
    m = re.search(r"Ran (\d+) tests", e)
    results.append({"check": "tests", "ok": code == 0,
                    "detail": "%s 项，%.1f 秒，%s" % (m.group(1) if m else "?", time.time() - t, e.strip().splitlines()[-1])})
    code, o, _ = sh([sys.executable, "skills/closing-out/scripts/audit.py", "--exclude", "dev/eval-runs/*"])
    audit_result = json.loads(o)
    results.append({"check": "self-audit", "ok": audit_result["ok"], "detail": dict(audit_result["summary"], complete=audit_result["complete"])})
    # 外层 ZIP 校验是正式发布的必需闸门（无文件也应 FAIL）。
    try:
        checked = validate_outer(a.outer_zip)
    except (OSError, zipfile.BadZipFile, subprocess.TimeoutExpired) as e:
        checked = {"ok": False, "reason": str(e)}
    results.append({"check": "outer-zip-python-extract", "ok": checked["ok"], "detail": checked})
    ok = all(r["ok"] for r in results)
    print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
