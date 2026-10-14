#!/usr/bin/env python3
"""Build UTF-8 named standalone .skill bundles and the outer release ZIP (stdlib)."""
import argparse
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT.parent / "deciding-and-executing-v4.0.1.zip"
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache"}


def walk_files(root):
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in EXCLUDE_DIRS)
        for name in sorted(names):
            if not name.endswith(".pyc"):
                yield Path(folder) / name


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
    rootname = "deciding-and-executing-v4.0.1"
    # Destination is intentionally outside project tree to avoid packaging itself.
    output = a.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("外层 ZIP 必须位于仓库之外，避免把发布包自身递归打包")
    bundle(output, ROOT, rootname)
    print(output)


if __name__ == "__main__":
    main()
