"""Secret-pattern redaction for persisted API diagnostics."""

from __future__ import annotations

import re
from typing import Any


_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_*\-]{6,}\b")


def redact_api_secrets(value: Any) -> str:
    return _API_KEY_PATTERN.sub("<redacted_api_key>", str(value))
