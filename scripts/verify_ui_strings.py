from __future__ import annotations

import re
import sys
from pathlib import Path

SUSPICIOUS_MARKERS = (
    "\ufffd",
    "誘",
    "寃",
    "紐",
    "吏",
    "媛",
)

STRING_LINE_RE = re.compile(r"""(['"`]).*?\1""")
HTML_TEXT_RE = re.compile(r">([^<]+)<")
COMMENT_PREFIXES = ("//", "#", "/*", "*", "<!--")
JS_LIKE_SUFFIXES = {".js", ".ts", ".mjs", ".cjs"}
HTML_LIKE_SUFFIXES = {".html", ".htm", ".jinja", ".j2"}
SELF_NOISE_FILES = {"verify_ui_strings.py", "review_patch_against_contract.js"}


def is_known_noise(path: Path, line: str) -> bool:
    if path.name == "verify_ui_strings.py":
        stripped = line.strip()
        if "SUSPICIOUS_MARKERS" in line or stripped in {'"誘",', '"寃",', '"紐",', '"吏",', '"媛",', '"\\ufffd",'}:
            return True
    if path.name == "review_patch_against_contract.js" and "suspiciousPattern" in line:
        return True
    return False


def classify_runtime_issue(path: Path, line: str) -> bool:
    suffix = path.suffix.lower()
    stripped = line.strip()
    if not stripped or stripped.startswith(COMMENT_PREFIXES):
        return False

    if suffix in JS_LIKE_SUFFIXES:
        return bool(STRING_LINE_RE.search(line))
    if suffix in HTML_LIKE_SUFFIXES:
        return bool(HTML_TEXT_RE.search(line)) or "textContent" in line or "innerText" in line
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/verify_ui_strings.py <relative-path> [<relative-path> ...]")
        return 2

    root = Path(__file__).resolve().parent.parent
    has_error = False

    for rel in sys.argv[1:]:
        path = (root / rel).resolve()
        if not path.exists():
            print(f"[ERROR] missing: {rel}")
            has_error = True
            continue

        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            print(f"[ERROR] utf8 decode failed: {rel} ({exc})")
            has_error = True
            continue

        runtime_hits: list[str] = []
        warning_hits: list[str] = []
        for idx, line in enumerate(text.splitlines(), start=1):
            if is_known_noise(path, line):
                continue
            if not any(marker in line for marker in SUSPICIOUS_MARKERS):
                continue
            snippet = line.strip()
            if classify_runtime_issue(path, line):
                runtime_hits.append(f"L{idx}: {snippet[:160]}")
            else:
                warning_hits.append(f"L{idx}: {snippet[:160]}")

        if runtime_hits:
            print(f"[ERROR] runtime ui string corruption: {rel}")
            for hit in runtime_hits:
                print(f"  - {hit}")
            has_error = True
        elif warning_hits:
            print(f"[WARN] suspicious marker outside runtime string: {rel}")
            for hit in warning_hits:
                print(f"  - {hit}")
        else:
            print(f"[OK] {rel}")

    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
