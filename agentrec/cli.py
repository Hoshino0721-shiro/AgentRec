"""Command-line demos for the offline AgentRec shopping loop."""

from __future__ import annotations

import argparse
import json
from typing import Iterable

from agentrec.agent.orchestrator import ShoppingAgent
from agentrec.simulation.scenarios import SCENARIOS, build_tasks
from agentrec.tools.catalog import CatalogTool, load_catalog


def demo(scenario: str, system: str, seed: int, as_json: bool) -> int:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {', '.join(SCENARIOS)}")
    task = build_tasks(count=1, seed=seed, scenarios=[scenario])[0]
    agent = ShoppingAgent(
        system=system,
        catalog=CatalogTool(load_catalog()),
        seed=seed,
    )
    record = agent.run_task(task)
    if as_json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    print(f"Scenario: {record['scenario']} ({'controlled' if task.controlled else 'non-controlled'})")
    print(f"Request: {task.request}")
    print("Action path: " + " -> ".join(step["selected_action"] for step in record["trajectory"]))
    print("Final products: " + (", ".join(record["final_product_ids"]) or "none"))
    print("Answer: " + record["final_answer"])
    print(
        "Primary metrics: "
        + json.dumps(
            {
                key: record["metrics"].get(key)
                for key in (
                    "task_success_rate",
                    "hard_constraint_satisfaction_rate",
                    "profile_contamination_rate",
                    "recovery_success_rate",
                )
            },
            ensure_ascii=False,
        )
    )
    print(f"Memory writes: {len(record['memory_writes'])}; saved trajectory steps: {len(record['trajectory'])}")
    return 0


def parse_args(argv: Iterable[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo", help="run one auditable controlled scenario")
    demo_parser.add_argument("--scenario", default="recipient_shift", choices=list(SCENARIOS))
    demo_parser.add_argument("--system", default="full_agent")
    demo_parser.add_argument("--seed", type=int, default=42)
    demo_parser.add_argument("--json", action="store_true", help="print the complete trajectory")
    return parser.parse_args(argv)


def main(argv: Iterable[str] = None) -> int:
    args = parse_args(argv)
    if args.command == "demo":
        return demo(args.scenario, args.system, args.seed, args.json)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

