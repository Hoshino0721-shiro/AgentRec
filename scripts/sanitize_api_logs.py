"""Redact API-key-shaped strings from already persisted AgentRec diagnostics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentrec.llm.security import redact_api_secrets


def sanitize(root: Path) -> int:
    changed = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        safe = redact_api_secrets(text)
        if safe != text:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(safe, encoding="utf-8")
            temporary.replace(path)
            changed += 1
    return changed


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    print("sanitized_files=%d" % sanitize(args.root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
