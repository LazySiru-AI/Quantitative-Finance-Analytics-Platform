"""Turn a pytest JUnit XML report into GitHub Actions error annotations.

Annotations are visible on the run's summary page (and through the public checks API) without
downloading logs, which is the point: a failing test on a public repository should say which test
failed and why to anyone looking at it.

Usage: python tools/ci_junit_annotations.py report.xml   (always exits 0; the pytest step fails the job)
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

#: GitHub shows at most this many annotations per step; the rest are summarised in one line.
MAX_ANNOTATIONS = 50


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(path: str) -> int:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::warning::no JUnit report at {path}: {exc}")
        return 0
    failures = []
    for case in root.iter("testcase"):
        for tag in ("failure", "error"):
            node = case.find(tag)
            if node is not None:
                name = f"{case.get('classname', '')}::{case.get('name', '')}"
                detail = (node.get("message") or node.text or "").strip()
                failures.append((case.get("file") or "", name, detail[:1500]))
    for file, name, detail in failures[:MAX_ANNOTATIONS]:
        location = f" file={file}" if file else ""
        print(f"::error{location},title={_escape(name)}::{_escape(detail)}")
    if len(failures) > MAX_ANNOTATIONS:
        print(f"::error::{len(failures) - MAX_ANNOTATIONS} more failures not annotated")
    print(f"{len(failures)} failing test(s) annotated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "pytest-report.xml"))
