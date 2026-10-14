from pathlib import Path

def safe_path(root, requested):
    return Path(root) / requested  # syntactically fine, unsafe for traversal
