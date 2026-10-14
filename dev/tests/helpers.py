"""测试公共工具：与使用者的 git 全局配置隔离，避免签名、钩子、编辑器导致超时或失败。"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DE = os.path.join(REPO, "skills", "deciding-and-executing", "scripts", "de.py")
AUDIT = os.path.join(REPO, "skills", "closing-out", "scripts", "audit.py")

ENV = dict(os.environ)
ENV.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"})


def git(cwd, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"] + list(args),
                   cwd=cwd, check=True, capture_output=True, env=ENV, timeout=30)


def init_repo(path):
    git(path, "init", "-q")
    git(path, "commit", "-q", "--allow-empty", "-m", "init")


def commit_all(path, msg="c"):
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", msg, "--allow-empty")


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p) or root, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def call(script, cwd, *args, timeout=60):
    r = subprocess.run([sys.executable, script] + list(args), cwd=cwd, capture_output=True, text=True,
                       env=ENV, timeout=timeout)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = {"_raw": r.stdout, "_err": r.stderr}
    return r.returncode, data
