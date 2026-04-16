from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
TYPE_RE = re.compile(r'type\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
SRC_RE = re.compile(r"\bsrc\s*=", re.IGNORECASE)
JINJA_BLOCK_RE = re.compile(r"\{#-?[\s\S]*?-?#\}|\{%-?[\s\S]*?-?%\}|\{\{-?[\s\S]*?-?\}\}")


def should_check(attrs: str) -> bool:
    if SRC_RE.search(attrs):
        return False
    match = TYPE_RE.search(attrs or "")
    if not match:
        return True
    value = (match.group(1) or "").strip().lower()
    if not value:
        return True
    if value in {"application/javascript", "text/javascript", "module"}:
        return True
    return False


def sanitize_jinja(text: str) -> str:
    return JINJA_BLOCK_RE.sub("0", text)


def normalize_error_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"[A-Za-z]:\\[^\n]+?\.js", "<temp>.js", cleaned)
    cleaned = re.sub(r"/tmp/[^ \n]+?\.js", "<temp>.js", cleaned)
    cleaned = re.sub(r"\n+", "\n", cleaned)
    return cleaned


def run_check(path: Path) -> list[str]:
    if path.suffix.lower() not in {".html", ".htm"}:
        return []
    if not path.exists():
        return [f"{path}: file not found"]

    text = path.read_text(encoding="utf-8").replace("\ufeff", "")
    chunks: list[str] = []
    for index, match in enumerate(SCRIPT_RE.finditer(text), start=1):
        attrs = match.group(1) or ""
        body = match.group(2) or ""
        if not should_check(attrs):
            continue
        sanitized = sanitize_jinja(body).strip()
        if not sanitized:
            continue
        chunks.append(f"// file: {path.as_posix()} script:{index}\n{sanitized}\n")

    if not chunks:
        return []

    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write("\n".join(chunks))

    try:
        proc = subprocess.run(
            ["node", "--check", str(temp_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        temp_path.unlink(missing_ok=True)

    if proc.returncode == 0:
        return []

    stderr = normalize_error_text(proc.stderr or proc.stdout or "")
    return [f"{path}: inline script syntax check failed", stderr]


def resolve_baseline_path(path_str: str, baseline_root: Path | None) -> Path | None:
    if baseline_root is None:
        return None
    original = Path(path_str)
    if original.is_absolute():
        try:
            rel = original.resolve().relative_to(Path.cwd().resolve())
        except Exception:
            return None
    else:
        rel = original
    candidate = (baseline_root / rel).resolve()
    return candidate


def check_file(path_str: str, baseline_root: Path | None = None) -> list[str]:
    path = Path(path_str)
    current_problem = run_check(path)
    if not current_problem:
        return []

    baseline_path = resolve_baseline_path(path_str, baseline_root)
    if baseline_path and baseline_path.exists():
        baseline_problem = run_check(baseline_path)
        if baseline_problem:
            current_signature = "\n".join(current_problem[1:]).strip()
            baseline_signature = "\n".join(baseline_problem[1:]).strip()
            if current_signature == baseline_signature:
                return []
            return current_problem + [
                f"{path}: baseline inline script syntax differs from current file",
                *baseline_problem[1:],
            ]

    return current_problem


def main(argv: list[str]) -> int:
    args = argv[1:]
    baseline_root: Path | None = None
    paths: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--baseline-root":
            if index + 1 >= len(args):
                print("--baseline-root requires a value", file=sys.stderr)
                return 2
            baseline_root = Path(args[index + 1]).resolve()
            index += 2
            continue
        paths.append(token)
        index += 1

    if not paths:
        print("usage: verify_template_inline_scripts.py <relative-path> [...]", file=sys.stderr)
        return 2

    problems: list[str] = []
    for path_str in paths:
        problems.extend(check_file(path_str, baseline_root))

    if problems:
        for item in problems:
            print(item, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
