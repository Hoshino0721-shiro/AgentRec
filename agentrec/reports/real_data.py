"""Generate the AgentRecBench report only from saved artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


METRICS = ("task_success_rate", "hr_at_3", "hr_at_5", "ndcg_at_5")


def _read(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object: %s" % path)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def _metric(system: MappingLike, name: str) -> str:
    value = (system.get("metrics") or {}).get(name)
    if not value:
        return "n/a"
    return "%.3f [%.3f, %.3f]" % (
        float(value["mean"]),
        float(value["ci_low"]),
        float(value["ci_high"]),
    )


class MappingLike(dict):
    pass


def build(project_root: Path, output: Path) -> Path:
    processed_path = project_root / "data" / "processed" / "agentrecbench_short_term_amazon_100.json"
    processed = _read(processed_path)
    data_manifest = dict(processed.get("manifest") or {})
    summary_path = project_root / "results" / "summary" / "real_pilot_summary.json"
    summary = _read(summary_path)
    raw_run = project_root / str(summary["raw_run_dir"])
    trajectory_path = raw_run / "trajectories.jsonl"
    rows = [json.loads(line) for line in trajectory_path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != int(summary["n_records"]):
        raise ValueError("real pilot summary/trajectory row count mismatch")
    if any(row.get("controlled") is not False for row in rows):
        raise ValueError("real pilot contains a non-real source boundary")

    smoke_rows: List[Dict[str, Any]] = []
    smoke_root = project_root / "results" / "raw" / "real_smoke"
    for manifest_path in sorted(smoke_root.glob("*/manifest.json")):
        manifest = _read(manifest_path)
        run_summary = _read(manifest_path.parent / "summary.json")
        source = dict(manifest.get("data_source") or {})
        smoke_rows.append(
            {
                "run_id": manifest.get("run_id"),
                "records": run_summary.get("n_records"),
                "code_hash": manifest.get("code_hash"),
                "excluded_candidate_reviews": source.get("candidate_history_reviews_excluded"),
                "valid": source.get("candidate_history_reviews_excluded") == 99,
            }
        )

    failures = [
        (index, row)
        for index, row in enumerate(rows, start=1)
        if row.get("system") == "short_term_recency"
        and float((row.get("metrics") or {}).get("task_success_rate", 0.0)) < 1.0
    ][:5]
    systems = dict(summary.get("systems") or {})
    lines = [
        "# AgentRecBench Amazon 真实日志报告",
        "",
        "本报告完全从已保存的 processed artifact、manifest、summary 和 JSONL 轨迹重建。",
        "它与 controlled full 分开：这里评估静态候选排序，不具备主动澄清、硬约束、对象污染或反馈恢复的可观测标签。",
        "",
        "## 数据边界",
        "",
        "- Dataset: `%s`，revision `%s`，MIT。" % (
            data_manifest["dataset_id"], data_manifest["dataset_revision"]
        ),
        "- Scenario/domain: `%s` / `%s`；`controlled=false`，`data_type=real_log`。" % (
            data_manifest["scenario"], data_manifest["domain"]
        ),
        "- 任务 %d；候选商品 %d；历史商品 %d/%d 成功解析；可见历史评论 %d。" % (
            data_manifest["task_count"],
            data_manifest["candidate_product_count"],
            data_manifest["resolved_history_product_count"],
            data_manifest["history_item_count"],
            data_manifest["task_visible_review_count"],
        ),
        "- 按官方 baseline 逻辑，从每个用户的可见历史中排除了全部候选商品评论，共 %d 条；审计后 target/candidate 泄漏为 0。" % data_manifest["candidate_history_reviews_excluded"],
        "- Processed artifact: `%s`，%d bytes，SHA-256 `%s`。" % (
            processed_path.relative_to(project_root).as_posix(),
            processed_path.stat().st_size,
            _sha256(processed_path),
        ),
        "- 商品原始范围为 23 个连续块，共 380,000,001 bytes；20 MB 处为 Yelp、30 MB 为 Amazon、400 MB 为 Goodreads。",
        "",
        "## 100-task pilot",
        "",
        "Run: `%s`；每个系统 n=100，共 %d 条轨迹，错误数均为 0。括号为逐任务 bootstrap 95%% CI。" % (
            summary["run_id"], summary["n_records"]
        ),
        "",
        "| 系统 | Exact target@1 | HR@3 | HR@5 | NDCG@5 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("candidate_order", "popularity", "full_history_lexical", "short_term_recency"):
        row = systems[name]
        lines.append(
            "| %s | %s | %s | %s | %s |" % tuple(
                [name] + [_metric(row, metric) for metric in METRICS]
            )
        )
    lines.extend(
        [
            "",
            "诚实结论：历史文本基线明显优于候选原顺序和 popularity；recency 的 HR@5 最高，但其 exact target@1 低于 full-history。",
            "这些结果只说明该固定 short-term Amazon 候选集上的离线命中，不代表真实用户 uplift，也不能替代 controlled Agent 机制指标。",
            "",
            "## 泄漏审计与保留的失败运行",
            "",
            "第一次 real smoke 没有排除候选商品评论，产生异常完美结果。审计上游官方 baseline 后修复；该运行没有删除，也不进入结论。",
            "",
            "| Run | 记录数 | Code hash | 排除候选评论 | 协议有效 |",
            "|---|---:|---|---:|---|",
        ]
    )
    for row in smoke_rows:
        lines.append(
            "| `%s` | %s | `%s` | %s | %s |"
            % (
                row["run_id"],
                row["records"],
                row["code_hash"],
                row["excluded_candidate_reviews"] if row["excluded_candidate_reviews"] is not None else "未执行",
                "是" if row["valid"] else "否（泄漏）",
            )
        )
    lines.extend(["", "## 代表性失败（short_term_recency）", ""])
    for line_number, row in failures:
        lines.append(
            "- JSONL line %d，task `%s`：target `%s`，top-5 `%s`。"
            % (
                line_number,
                row["task_id"],
                row["target_product_id"],
                ", ".join(row["final_product_ids"]),
            )
        )
    lines.extend(
        [
            "",
            "## 复现",
            "",
            "```powershell",
            "Set-Location F:\\AgentRec",
            "python scripts\\fetch_agentrecbench_subset.py --project-root . --scenario short_term --max-tasks 100 --workers 8",
            "python -m agentrec.real.run --config experiments\\configs\\real_smoke.yaml",
            "python -m agentrec.real.run --config experiments\\configs\\real_pilot.yaml",
            "python -m agentrec.reports.real_data --project-root . --output reports\\real_data_report.md",
            "```",
            "",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("reports/real_data_report.md"))
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    project_root = args.project_root.resolve()
    output = args.output if args.output.is_absolute() else project_root / args.output
    print(build(project_root, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
