#!/usr/bin/env python3
"""Build UTF-8 named standalone .skill bundles and the outer release ZIP (stdlib)."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def skill_version(name="deciding-and-executing"):
    """版本号的唯一来源是各技能 SKILL.md 的 metadata.version。"""
    text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r'^\s*version:\s*"?([\w.-]+)"?', text, re.M)
    if not m:
        raise SystemExit("skills/%s/SKILL.md 缺少 metadata.version" % name)
    return m.group(1)


RELEASE_NAME = "deciding-and-executing-v" + skill_version()
DEFAULT_OUTPUT = ROOT.parent / (RELEASE_NAME + ".zip")
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache"}


def git_visible(root):
    """root 下未被 Git 忽略的文件（相对 root 的 POSIX 路径）；不在 Git 仓库里时返回 None。"""
    try:
        r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           cwd=root, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return {os.fsdecode(n) for n in r.stdout.split(b"\0") if n}


def walk_files(root):
    """要打包的文件：跳过缓存目录，在 Git 仓库里还跳过被忽略的文件（本地日志、私有数据不进发布包）。"""
    root = Path(root)
    visible = git_visible(root)
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in EXCLUDE_DIRS)
        for name in sorted(names):
            p = Path(folder) / name
            if name.endswith(".pyc") or (visible is not None and p.relative_to(root).as_posix() not in visible):
                continue
            yield p


def bundle(dst, base, prefix):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in walk_files(base):
            z.write(p, str(Path(prefix) / p.relative_to(base)).replace(os.sep, "/"))
        # Python zipfile sets the UTF-8 flag on non-ASCII member names.


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    a = ap.parse_args()
    for name in ("deciding-and-executing", "closing-out"):
        bundle(ROOT / "dist" / (name + ".skill"), ROOT / "skills" / name, name)
    rootname = RELEASE_NAME
    # Destination is intentionally outside project tree to avoid packaging itself.
    output = a.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("外层 ZIP 必须位于仓库之外，避免把发布包自身递归打包")
    bundle(output, ROOT, rootname)
    print(output)


if __name__ == "__main__":
    main()
