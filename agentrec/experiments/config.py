"""Configuration loading and immutable run identity helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name == "AGENTREC_MODEL":
                return os.environ.get(name, "offline-deterministic-policy")
            return os.environ.get(name, match.group(0))

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def load_config(path: str) -> Tuple[Dict[str, Any], str]:
    """Load YAML, resolve permitted environment placeholders, and hash content."""
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("experiment config must contain a YAML mapping")
    config = _expand_env(raw)
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return config, digest


def git_commit(project_root: Path) -> str:
    """Return the code revision without failing in exported source trees."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        baseline = project_root / "BASELINE_COMMIT"
        if baseline.exists():
            value = baseline.read_text(encoding="utf-8").strip()
            if value:
                return value
        return "unknown"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def code_fingerprint(project_root: Path) -> str:
    """Hash executable source/config files so dirty-tree runs remain identifiable."""
    digest = hashlib.sha256()
    candidates = []
    for relative_root in ("agentrec", "experiments/configs", "tests"):
        root = project_root / relative_root
        if root.exists():
            candidates.extend(path for path in root.rglob("*") if path.is_file())
    upstream_patch = project_root / "upstream" / "bearcode" / "agents" / "agent.py"
    if upstream_patch.exists():
        candidates.append(upstream_patch)
    baseline = project_root / "BASELINE_COMMIT"
    if baseline.exists():
        candidates.append(baseline)
    for relative in ("data/processed/catalog.json", "pyproject.toml", "requirements.txt"):
        artifact = project_root / relative
        if artifact.exists():
            candidates.append(artifact)
    for path in sorted(set(candidates), key=lambda item: str(item.relative_to(project_root)).lower()):
        if "__pycache__" in path.parts or path.name.endswith((".pyc", ".pyo")):
            continue
        relative = str(path.relative_to(project_root)).replace("\\", "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]
