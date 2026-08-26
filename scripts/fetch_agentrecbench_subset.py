"""Fetch and build the pinned minimal AgentRecBench Amazon subset.

The script is resumable.  It downloads 100 short-term task/ground-truth pairs,
the 21.9 MB short-term review JSONL, and only a byte envelope that fully
contains the Amazon portion of the 1.36 GB item JSONL.  Exact adjacent range
chunks are retained for provenance and reassembled by the data adapter while
parsing, so the full source file is never downloaded.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentrec.data.agentrecbench import (
    AGENTRECBENCH_DATASET_ID,
    AGENTRECBENCH_REVISION,
    build_processed_subset,
    load_processed_subset,
)


BASE_URL = (
    "https://huggingface.co/datasets/%s/resolve/%s"
    % (AGENTRECBENCH_DATASET_ID, AGENTRECBENCH_REVISION)
)
ITEM_RANGE_START = 20_000_000
ITEM_RANGE_END = 400_000_000
DEFAULT_CHUNK_BYTES = 16 * 1024 * 1024
USER_AGENT = "AgentRec-reproducible-subset/1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _request(url: str, byte_range: Optional[Tuple[int, int]] = None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    if byte_range is not None:
        headers["Range"] = "bytes=%d-%d" % byte_range
    return urllib.request.Request(url, headers=headers)


def _promote(temporary: Path, destination: Path) -> None:
    """Handle short-lived Windows scanner/indexer locks after close()."""

    last_error: Optional[BaseException] = None
    for retry in range(12):
        try:
            temporary.replace(destination)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.1 * (retry + 1))
    if last_error is not None:
        raise last_error


def _download(
    url: str,
    destination: Path,
    *,
    byte_range: Optional[Tuple[int, int]] = None,
    attempts: int = 6,
) -> Path:
    expected = None if byte_range is None else byte_range[1] - byte_range[0] + 1
    if destination.exists() and destination.stat().st_size > 0:
        if expected is None or destination.stat().st_size == expected:
            return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(_request(url, byte_range), timeout=120) as response:
                status = int(getattr(response, "status", response.getcode()))
                content_range = response.headers.get("Content-Range")
                if byte_range is not None:
                    expected_prefix = "bytes %d-%d/" % byte_range
                    if status != 206 or not str(content_range or "").startswith(expected_prefix):
                        raise RuntimeError(
                            "range request was not honoured: status=%s content-range=%s"
                            % (status, content_range)
                        )
                with temporary.open("wb") as stream:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        stream.write(block)
            if expected is not None and temporary.stat().st_size != expected:
                raise RuntimeError(
                    "range size mismatch for %s: expected %d, got %d"
                    % (destination.name, expected, temporary.stat().st_size)
                )
            _promote(temporary, destination)
            return destination
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
            if attempt == attempts:
                raise RuntimeError("download failed after %d attempts: %s" % (attempts, url)) from exc
            delay = min(30.0, (2.0 ** (attempt - 1)) + random.random())
            print("retry %d/%d in %.1fs: %s" % (attempt, attempts, delay, destination.name), flush=True)
            time.sleep(delay)
    raise AssertionError("unreachable")


def _task_jobs(task_root: Path, scenario: str, max_tasks: int):
    for index in range(max_tasks):
        yield (
            "%s/task/%s/amazon/tasks/task_%d.json?download=true"
            % (BASE_URL, scenario, index),
            task_root / "tasks" / ("task_%d.json" % index),
            None,
        )
        yield (
            "%s/task/%s/amazon/groundtruth/groundtruth_%d.json?download=true"
            % (BASE_URL, scenario, index),
            task_root / "groundtruth" / ("groundtruth_%d.json" % index),
            None,
        )


def _range_jobs(range_root: Path, chunk_bytes: int):
    start = ITEM_RANGE_START
    while start <= ITEM_RANGE_END:
        end = min(ITEM_RANGE_END, start + chunk_bytes - 1)
        yield (
            "%s/output_data_short/item.json?download=true" % BASE_URL,
            range_root / ("item_%012d_%012d.bin" % (start, end)),
            (start, end),
        )
        start = end + 1


def _run_jobs(jobs, workers: int, label: str) -> List[Path]:
    job_list = list(jobs)
    paths: List[Path] = []
    print("%s: %d files" % (label, len(job_list)), flush=True)
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {
            pool.submit(_download, url, destination, byte_range=byte_range): destination
            for url, destination, byte_range in job_list
        }
        completed = 0
        for future in as_completed(futures):
            path = future.result()
            paths.append(path)
            completed += 1
            if completed == len(job_list) or completed % 10 == 0:
                print("%s: %d/%d" % (label, completed, len(job_list)), flush=True)
    return paths


def fetch(
    project_root: Path,
    *,
    scenario: str,
    max_tasks: int,
    workers: int,
    chunk_bytes: int,
) -> Path:
    external_root = project_root / "data" / "external" / "AgentRecBenchDataset"
    task_root = external_root / "task" / scenario / "amazon"
    range_root = external_root / "raw_ranges" / "output_data_short_item"
    review_path = external_root / "output_data_short" / "review.json"
    output_path = project_root / "data" / "processed" / (
        "agentrecbench_%s_amazon_%d.json" % (scenario, max_tasks)
    )

    _run_jobs(_task_jobs(task_root, scenario, max_tasks), workers, "tasks")
    _download(
        "%s/output_data_short/review.json?download=true" % BASE_URL,
        review_path,
    )
    print("reviews: %d bytes" % review_path.stat().st_size, flush=True)
    item_chunks = _run_jobs(_range_jobs(range_root, chunk_bytes), workers, "item ranges")
    item_chunks.sort(key=lambda path: path.name)

    build_processed_subset(
        task_root=task_root,
        item_chunks=item_chunks,
        review_path=review_path,
        output_path=output_path,
        scenario=scenario,
        max_tasks=max_tasks,
        provenance={
            "downloaded_at": _utc_now(),
            "download_method": "pinned_huggingface_resolve_with_exact_http_ranges",
            "item_byte_envelope": {
                "start_inclusive": ITEM_RANGE_START,
                "end_inclusive": ITEM_RANGE_END,
                "chunk_bytes": chunk_bytes,
                "boundary_evidence": {
                    "offset_20000000": "yelp",
                    "offset_30000000": "amazon",
                    "offset_400000000": "goodreads",
                },
            },
        },
    )
    subset = load_processed_subset(output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "tasks": len(subset.tasks),
                "products": len(subset.products),
                "reviews": len(subset.reviews),
                "controlled": subset.manifest["controlled"],
                "dataset_revision": subset.manifest["dataset_revision"],
            },
            indent=2,
        ),
        flush=True,
    )
    return output_path


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--scenario", default="short_term", choices=["short_term"])
    parser.add_argument("--max-tasks", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    if args.max_tasks < 1 or args.max_tasks > 100:
        raise ValueError("max-tasks must be between 1 and 100")
    if args.chunk_bytes < 1024 * 1024:
        raise ValueError("chunk-bytes must be at least 1 MiB")
    fetch(
        args.project_root.resolve(),
        scenario=args.scenario,
        max_tasks=args.max_tasks,
        workers=args.workers,
        chunk_bytes=args.chunk_bytes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
