from __future__ import annotations

import re
import sys
from pathlib import Path


SUSPICIOUS_MARKERS = (
    "??",
    "\ufffd",
    "瓴",
    "歆",
    "臧",
    "氙",
)

JS_LIKE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_TEXTUAL_SEGMENT_PATTERN = re.compile(
    r"//.*?$|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
    re.MULTILINE | re.DOTALL,
)
JS_NULLISH_PATTERN = re.compile(r"(?<=\S)\s*\?\?\s*(?=\S)")


def get_marker_haystack(path: Path, text: str, marker: str) -> str:
    if path.name == "verify_file_safety.py":
        return ""
    if marker == "??" and path.suffix.lower() in JS_LIKE_EXTENSIONS:
        haystack = "\n".join(match.group(0) for match in JS_TEXTUAL_SEGMENT_PATTERN.finditer(text))
        return JS_NULLISH_PATTERN.sub(" ", haystack)
    return text


def format_marker(marker: str) -> str:
    try:
        marker.encode("cp949")
        return marker
    except UnicodeEncodeError:
        return marker.encode("unicode_escape").decode("ascii")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/verify_file_safety.py <relative-path> [<relative-path> ...]")
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
        bom = raw.startswith(b"\xef\xbb\xbf")

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            print(f"[ERROR] utf8 decode failed: {rel} ({exc})")
            has_error = True
            continue

        issues: list[str] = []
        if bom:
            issues.append("BOM detected")

        for marker in SUSPICIOUS_MARKERS:
            haystack = get_marker_haystack(path, text, marker)
            if marker in haystack:
                issues.append(f"suspicious marker: {format_marker(marker)}")

        if issues:
            print(f"[WARN] {rel}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"[OK] {rel}")

    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
