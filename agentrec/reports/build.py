"""Build an evidence-linked Markdown report from raw JSONL trajectories."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from agentrec.experiments.metrics import (
    PRIMARY_METRICS,
    aggregate_records,
    classify_failure,
    paired_system_comparisons,
)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if isinstance(value, dict):
            value["_source_file"] = str(path)
            value["_source_line"] = line_number
            rows.append(value)
    return rows


def _read_json_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _independent_extension_lines(output: Path) -> List[str]:
    """Append separately scoped evidence without mixing it into controlled aggregates."""

    if output.parent.name != "reports":
        return []
    project_root = output.parent.parent
    real_path = project_root / "results" / "summary" / "real_pilot_summary.json"
    llm_pilot_path = project_root / "results" / "summary" / "llm_pilot_summary.json"
    llm_smoke_path = project_root / "results" / "summary" / "llm_smoke_summary.json"
    llm_path = llm_pilot_path if llm_pilot_path.exists() else llm_smoke_path
    if not real_path.exists() and not llm_path.exists():
        return []

    lines = [
        "",
        "## Independently scoped extensions",
        "",
        "The following runs use separate protocols and are not included in any controlled aggregate above.",
        "",
    ]
    if real_path.exists():
        real = _read_json_object(real_path)
        systems = dict(real.get("systems") or {})
        lines.extend(
            [
                "### AgentRecBench Amazon real-log ranking",
                "",
                f"Run `{real.get('run_id')}` contains {int(real.get('n_records') or 0)} saved records "
                "with `controlled=false`. Exact target@1 is a static ranking label, not interactive Agent task success.",
                "",
                "| System | n | Exact target@1 | HR@3 | HR@5 | NDCG@5 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for name in ("candidate_order", "popularity", "full_history_lexical", "short_term_recency"):
            system = systems.get(name, {})
            lines.append(
                f"| {name} | {int(system.get('n') or 0)} | "
                f"{_metric_cell(system, 'task_success_rate')} | {_metric_cell(system, 'hr_at_3')} | "
                f"{_metric_cell(system, 'hr_at_5')} | {_metric_cell(system, 'ndcg_at_5')} |"
            )
        lines.extend(
            [
                "",
                "Candidate-history leakage was found in the first smoke, fixed by excluding 99 candidate reviews, "
                "and the invalid run was retained. Full provenance, confidence intervals, and failures are in "
                "[the separate real-data report](real_data_report.md).",
                "",
            ]
        )

    if llm_path.exists():
        llm = _read_json_object(llm_path)
        budget = dict(llm.get("budget_after") or {})
        overall_budget = dict(llm.get("overall_budget_after") or budget)
        system = dict((llm.get("systems") or {}).get("llm_full_agent") or {})
        is_pilot = llm_path == llm_pilot_path
        stop_error = str(llm.get("stop_error") or "")
        if "401" in stop_error and "invalid_api_key" in stop_error:
            failure_note = "The first request returned `401 invalid_api_key` before inference."
        elif "403" in stop_error:
            failure_note = "The first request returned `403 permission_denied` before inference."
        elif llm.get("stop_reason") == "completed":
            failure_note = "The configured run completed; its task metrics are reported in the saved run summary."
        else:
            failure_note = "The run stopped before a complete inference-quality result was available."
        cost_basis = str(llm.get("cost_basis") or "")
        quality_note = (
            "" if llm.get("stop_reason") == "completed"
            else " No inference-quality result is claimed for a stopped run."
        )
        heading = "Paid LLM controlled pilot" if is_pilot else "Paid LLM preflight"
        lines.extend(
            [
                f"### {heading}",
                "",
                f"Run `{llm.get('run_id')}` requested model `{llm.get('model')}` and stopped with "
                f"`{llm.get('stop_reason')}` after saving {int(llm.get('saved_records') or 0)} record(s). "
                f"{failure_note}{quality_note}",
                "",
                f"The current-provider ledger reports ${float(budget.get('settled_cost_usd') or 0.0):.2f} settled. "
                f"Across all provider ledgers, ${float(overall_budget.get('charged_or_reserved_usd') or 0.0):.2f} "
                f"is charged/reserved and ${float(overall_budget.get('remaining_usd') or 0.0):.2f} remains. "
                "Saved errors are redacted.",
                "",
            ]
        )
        if is_pilot and system:
            lines.extend(
                [
                    "| n | Task success | Hard constraints | Profile contamination | Recovery success | Useful clarification | Mean tool calls |",
                    "|---:|---:|---:|---:|---:|---:|---:|",
                    f"| {int(system.get('n') or 0)} | {_metric_cell(system, 'task_success_rate')} | "
                    f"{_metric_cell(system, 'hard_constraint_satisfaction_rate')} | "
                    f"{_metric_cell(system, 'profile_contamination_rate')} | "
                    f"{_metric_cell(system, 'recovery_success_rate')} | "
                    f"{_metric_cell(system, 'useful_clarification_rate')} | "
                    f"{_metric_cell(system, 'mean_tool_calls')} |",
                    "",
                ]
            )
            trajectory_value = str(llm.get("trajectories_file") or "")
            trajectory_path = project_root / trajectory_value if trajectory_value else None
            if trajectory_path and trajectory_path.exists():
                llm_rows = _read_jsonl(trajectory_path)
                ignored_count = 0
                rows_with_ignored = 0
                useful_clarifications = 0
                useless_clarifications = 0
                input_tokens = 0
                cached_input_tokens = 0
                output_tokens = 0
                reference_cost = 0.0
                first_ignored = None
                first_useless_clarification = None
                for line_number, row in enumerate(llm_rows, start=1):
                    row_ignored = 0
                    for step in list(row.get("trajectory") or []):
                        tool_result = step.get("tool_result")
                        if isinstance(tool_result, dict):
                            row_ignored += len(tool_result.get("ignored_function_calls") or [])
                    ignored_count += row_ignored
                    rows_with_ignored += int(row_ignored > 0)
                    if row_ignored and first_ignored is None:
                        first_ignored = (str(row.get("task_id") or "unknown"), line_number)
                    clarification = (row.get("metrics") or {}).get("useful_clarification_rate")
                    useful_clarifications += int(clarification == 1)
                    useless_clarifications += int(clarification == 0)
                    if clarification == 0 and first_useless_clarification is None:
                        first_useless_clarification = (
                            str(row.get("task_id") or "unknown"),
                            line_number,
                        )
                    usage = dict(row.get("token_usage") or {})
                    input_tokens += int(usage.get("input") or 0)
                    cached_input_tokens += int(usage.get("cached_input") or 0)
                    output_tokens += int(usage.get("output") or 0)
                    reference_cost += float(row.get("estimated_cost_usd") or 0.0)
                lines.extend(
                    [
                        f"The {len(llm_rows)} unfiltered pilot trajectories contain {input_tokens:,} input, "
                        f"{cached_input_tokens:,} cached-input, and {output_tokens:,} output tokens; their "
                        f"OpenAI-price reference estimate totals ${reference_cost:.4f}.",
                        "",
                        f"Negative mechanism signals are retained: {ignored_count} extra provider tool calls occurred "
                        f"across {rows_with_ignored} task(s) despite `parallel_tool_calls=false` and were logged then "
                        f"suppressed to preserve one audited action per turn. Of "
                        f"{useful_clarifications + useless_clarifications} executed clarifications, "
                        f"{useful_clarifications} added information and {useless_clarifications} did not.",
                        "",
                    ]
                )
                examples = []
                if first_ignored:
                    examples.append(
                        f"extra-call example `{first_ignored[0]}` at "
                        f"`{trajectory_value}:{first_ignored[1]}`"
                    )
                if first_useless_clarification:
                    examples.append(
                        f"no-new-information clarification example `{first_useless_clarification[0]}` at "
                        f"`{trajectory_value}:{first_useless_clarification[1]}`"
                    )
                if examples:
                    lines.extend(["Representative audit records: " + "; ".join(examples) + ".", ""])
        if cost_basis:
            lines.extend([f"Cost basis: {cost_basis}. This is not the gateway's verified invoice price.", ""])
    return lines


def discover_records(results_root: Path) -> List[Dict[str, Any]]:
    files = sorted(results_root.rglob("trajectories.jsonl"))
    records: List[Dict[str, Any]] = []
    for path in files:
        rows = _read_jsonl(path)
        for row in rows:
            row["_source_mtime"] = path.stat().st_mtime
        records.extend(rows)
    return records


def _metric_cell(summary: Mapping[str, Any], name: str) -> str:
    metric = (summary.get("metrics") or {}).get(name)
    if not metric:
        return "—"
    return f"{metric['mean']:.3f} [{metric['ci_low']:.3f}, {metric['ci_high']:.3f}]"


def _latest_stage(records: Sequence[Mapping[str, Any]]) -> str:
    stages = {str(row.get("stage") or "unknown") for row in records}
    if "full" in stages:
        return "full"
    if "pilot" in stages:
        return "pilot"
    if "smoke" in stages:
        return "smoke"
    return sorted(stages)[-1] if stages else "unknown"


def _conclusion(systems: Mapping[str, Any]) -> List[str]:
    fixed = systems.get("fixed_pipeline", {}).get("metrics", {})
    full = systems.get("full_agent", {}).get("metrics", {})
    lines: List[str] = []
    if fixed and full:
        for metric in PRIMARY_METRICS:
            left = full.get(metric, {}).get("mean")
            right = fixed.get(metric, {}).get("mean")
            if left is None or right is None:
                continue
            direction = "lower is better" if metric == "profile_contamination_rate" else "higher is better"
            lines.append(
                f"- `{metric}`: full Agent {left:.3f} vs fixed pipeline {right:.3f} "
                f"(absolute difference {left - right:+.3f}; {direction})."
            )
    if not lines:
        lines.append("- The available stage does not contain both fixed-pipeline and full-Agent rows; no such comparison is claimed.")
    ablation_metrics = {
        "ablation_no_clarification": "task_success_rate",
        "ablation_no_replanning": "task_success_rate",
        "ablation_no_recipient_isolation": "profile_contamination_rate",
        "ablation_no_temporal_decay": "stale_memory_misuse_rate",
    }
    for system, metric in ablation_metrics.items():
        full_value = full.get(metric, {}).get("mean")
        ablated_value = systems.get(system, {}).get("metrics", {}).get(metric, {}).get("mean")
        if full_value is None or ablated_value is None:
            continue
        lines.append(
            f"- `{system}`: `{metric}` was {ablated_value:.3f} versus {full_value:.3f} for the full Agent "
            f"(full minus ablation {full_value - ablated_value:+.3f})."
        )
    return lines


def build_report(records: Sequence[Mapping[str, Any]], output: Path) -> None:
    if not records:
        raise ValueError("no trajectories.jsonl records found; refusing to create a result report")
    stage = _latest_stage(records)
    stage_rows = [row for row in records if str(row.get("stage") or "unknown") == stage]
    run_mtimes: Dict[str, float] = {}
    for row in stage_rows:
        run_id = str(row.get("run_id") or "unknown")
        run_mtimes[run_id] = max(run_mtimes.get(run_id, 0.0), float(row.get("_source_mtime") or 0.0))
    latest_run_id = max(run_mtimes, key=run_mtimes.get)
    selected = [row for row in stage_rows if str(row.get("run_id") or "unknown") == latest_run_id]
    first = selected[0]
    bootstrap_samples = int(first.get("bootstrap_samples") or 2000)
    confidence = float(first.get("confidence_level") or 0.95)
    aggregate = aggregate_records(
        selected,
        bootstrap_samples=bootstrap_samples,
        confidence=confidence,
        seed=20260824,
    )
    systems = aggregate["systems"]
    paired = paired_system_comparisons(
        selected,
        reference="full_agent",
        bootstrap_samples=bootstrap_samples,
        confidence=confidence,
        seed=20260824,
    ) if "full_agent" in systems else {}
    controlled_count = sum(bool(row.get("controlled")) for row in selected)
    noncontrolled_count = len(selected) - controlled_count
    scenarios = Counter(str(row.get("scenario") or "unknown") for row in selected)
    failures = [row for row in selected if classify_failure(row) != "success"]

    lines = [
        "# AgentRec Final Experimental Report",
        "",
        "## Scope and provenance",
        "",
        f"This report was generated from **{len(selected)} unfiltered per-task records** in the `{stage}` stage. "
        "Every aggregate below is computed from saved JSONL trajectories; no result is manually entered.",
        "",
        f"- Controlled task records: {controlled_count}",
        f"- Non-controlled/real-log records: {noncontrolled_count}",
        f"- Run ID: {latest_run_id}",
        f"- Configuration hash(es): {', '.join(sorted({str(row.get('config_hash')) for row in selected}))}",
        f"- Code revision(s): {', '.join(sorted({str(row.get('git_commit')) for row in selected}))}",
        f"- Dirty-tree code fingerprint(s): {', '.join(sorted({str(row.get('code_hash')) for row in selected}))}",
        f"- Seeds: {', '.join(str(value) for value in sorted({int(row.get('seed', 0)) for row in selected}))}",
        f"- Bootstrap: {bootstrap_samples} resamples, {confidence:.0%} percentile interval",
        f"- Runtime-error records: {sum(bool(row.get('error')) for row in selected)}",
        "",
    ]
    if noncontrolled_count == 0:
        lines.extend([
            "> **External-validity boundary:** all reported tasks are controlled, deterministic shopping tasks. "
            "These results establish mechanism behavior and reproducibility, not production recommendation quality or real-user uplift.",
            "",
        ])

    lines.extend(["## Scenario coverage", "", "| Scenario | Records |", "|---|---:|"])
    for scenario, count in sorted(scenarios.items()):
        lines.append(f"| {scenario} | {count} |")

    lines.extend([
        "",
        "## Primary results",
        "",
        "Values are means with bootstrap 95% confidence intervals. Profile contamination is lower-is-better; the other primary metrics are higher-is-better.",
        "",
        "| System | n | Task success | Hard constraints | Profile contamination | Recovery success |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for system, summary in systems.items():
        lines.append(
            f"| {system} | {summary['n']} | "
            f"{_metric_cell(summary, 'task_success_rate')} | "
            f"{_metric_cell(summary, 'hard_constraint_satisfaction_rate')} | "
            f"{_metric_cell(summary, 'profile_contamination_rate')} | "
            f"{_metric_cell(summary, 'recovery_success_rate')} |"
        )

    if paired:
        lines.extend([
            "",
            "## Paired differences: full Agent minus comparison",
            "",
            "Negative profile-contamination differences favor the full Agent; positive differences favor it for the other primary metrics.",
            "",
            "| Comparison | Paired n | Task success Δ | Hard constraints Δ | Contamination Δ | Recovery Δ |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for system, comparison in paired.items():
            cells = []
            for metric in PRIMARY_METRICS:
                value = comparison["metrics"].get(metric)
                cells.append(
                    "—" if not value else f"{value['mean']:+.3f} [{value['ci_low']:+.3f}, {value['ci_high']:+.3f}]"
                )
            lines.append(
                f"| {system} | {comparison['common_episodes']} | " + " | ".join(cells) + " |"
            )

    lines.extend([
        "",
        "## Agent and recommendation diagnostics",
        "",
        "| System | HR@5 | NDCG@5 | Useful clarification | Memory write accuracy | Stale-memory misuse | Mean turns | Mean tool calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for system, summary in systems.items():
        lines.append(
            f"| {system} | {_metric_cell(summary, 'hr_at_5')} | {_metric_cell(summary, 'ndcg_at_5')} | "
            f"{_metric_cell(summary, 'useful_clarification_rate')} | {_metric_cell(summary, 'memory_write_accuracy')} | "
            f"{_metric_cell(summary, 'stale_memory_misuse_rate')} | {_metric_cell(summary, 'mean_turns')} | "
            f"{_metric_cell(summary, 'mean_tool_calls')} |"
        )

    lines.extend(["", "## Direct observations", ""])
    lines.extend(_conclusion(systems))
    lines.extend([
        "",
        "These differences describe this frozen controlled benchmark. A confidence interval overlapping zero, or equal point estimates, is retained as a zero result rather than reframed as an improvement.",
        "",
        "## Failure accounting",
        "",
        "| System | Failure category | Count |",
        "|---|---|---:|",
    ])
    for system, summary in systems.items():
        for category, count in summary["failure_counts"].items():
            lines.append(f"| {system} | {category} | {count} |")

    lines.extend([
        "",
        "### Deterministic failure examples",
        "",
        "The list shows the lexicographically first saved example for each system/failure-category pair; the table above counts every failure.",
        "",
    ])
    if failures:
        examples: Dict[tuple, Mapping[str, Any]] = {}
        for row in sorted(failures, key=lambda item: (str(item.get("system")), str(item.get("task_id")))):
            key = (str(row.get("system")), classify_failure(row))
            examples.setdefault(key, row)
        for row in list(examples.values())[:20]:
            lines.append(
                f"- `{row.get('system')}` / `{row.get('task_id')}` / `{row.get('scenario')}`: "
                f"{classify_failure(row)}; final products={row.get('final_product_ids')}; "
                f"source `{row.get('_source_file')}:{row.get('_source_line')}`."
            )
    else:
        lines.append("- No failed sample exists in this stage; this is reported as observed rather than assumed.")

    lines.extend([
        "",
        "## Reproduction",
        "",
        "```powershell",
        "python -m pytest -p no:cacheprovider",
        "python -m agentrec.cli demo --scenario recipient_shift",
        "python -m agentrec.experiments.run --config experiments/configs/smoke.yaml",
        "python -m agentrec.experiments.run --config experiments/configs/pilot.yaml",
        "python -m agentrec.experiments.run --config experiments/configs/full.yaml",
        "python -m agentrec.reports.build --results results/raw --output reports/final_report.md",
        "```",
    ])
    lines.extend(_independent_extension_lines(output))
    lines.extend([
        "",
        "Raw trajectories, including failures, remain under `results/raw/`. Aggregated tables can always be regenerated from those records.",
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="results/raw", help="directory containing trajectories.jsonl files")
    parser.add_argument("--output", default="reports/final_report.md", help="Markdown output path")
    return parser.parse_args(argv)


def main(argv: Iterable[str] = None) -> int:
    args = parse_args(argv)
    records = discover_records(Path(args.results))
    build_report(records, Path(args.output))
    print(f"wrote {args.output} from {len(records)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
