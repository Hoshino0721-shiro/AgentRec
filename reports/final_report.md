# AgentRec Final Experimental Report

## Scope and provenance

This report was generated from **8100 unfiltered per-task records** in the `full` stage. Every aggregate below is computed from saved JSONL trajectories; no result is manually entered.

- Controlled task records: 8100
- Non-controlled/real-log records: 0
- Run ID: agentrec_full-a6c5235444e80f7b-20260825T094146-76f830
- Configuration hash(es): a6c5235444e80f7b
- Code revision(s): 09facfe
- Dirty-tree code fingerprint(s): 74aa0137a3ef25c5
- Seeds: 42, 123, 2026
- Bootstrap: 2000 resamples, 95% percentile interval
- Runtime-error records: 0

> **External-validity boundary:** all reported tasks are controlled, deterministic shopping tasks. These results establish mechanism behavior and reproducibility, not production recommendation quality or real-user uplift.

## Scenario coverage

| Scenario | Records |
|---|---:|
| clear_single_turn | 1008 |
| cold_start | 999 |
| hard_constraints | 999 |
| needs_clarification | 1026 |
| preference_alignment | 1026 |
| preference_conflict | 1026 |
| recipient_shift | 1017 |
| rejection_recovery | 999 |

## Primary results

Values are means with bootstrap 95% confidence intervals. Profile contamination is lower-is-better; the other primary metrics are higher-is-better.

| System | n | Task success | Hard constraints | Profile contamination | Recovery success |
|---|---:|---:|---:|---:|---:|
| ablation_no_clarification | 900 | 0.937 [0.920, 0.951] | 0.937 [0.921, 0.952] | 0.000 [0.000, 0.000] | 0.747 [0.693, 0.804] |
| ablation_no_recipient_isolation | 900 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.126 [0.106, 0.148] | 1.000 [1.000, 1.000] |
| ablation_no_replanning | 900 | 0.877 [0.854, 0.897] | 0.877 [0.856, 0.898] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| ablation_no_temporal_decay | 900 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| agent_flat_memory | 900 | 0.750 [0.721, 0.777] | 0.750 [0.722, 0.778] | 0.126 [0.106, 0.148] | 0.000 [0.000, 0.000] |
| agent_hierarchical_memory | 900 | 0.750 [0.721, 0.777] | 0.750 [0.722, 0.778] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| agent_no_memory | 900 | 0.498 [0.466, 0.530] | 0.750 [0.722, 0.778] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| fixed_pipeline | 900 | 0.498 [0.466, 0.530] | 0.750 [0.722, 0.778] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| full_agent | 900 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |

## Paired differences: full Agent minus comparison

Negative profile-contamination differences favor the full Agent; positive differences favor it for the other primary metrics.

| Comparison | Paired n | Task success Δ | Hard constraints Δ | Contamination Δ | Recovery Δ |
|---|---:|---:|---:|---:|---:|
| ablation_no_clarification | 900 | +0.063 [+0.048, +0.079] | +0.063 [+0.048, +0.080] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| ablation_no_recipient_isolation | 900 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | -0.126 [-0.148, -0.104] | +0.000 [+0.000, +0.000] |
| ablation_no_replanning | 900 | +0.123 [+0.102, +0.143] | +0.123 [+0.102, +0.146] | +0.000 [+0.000, +0.000] | +1.000 [+1.000, +1.000] |
| ablation_no_temporal_decay | 900 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| agent_flat_memory | 900 | +0.250 [+0.222, +0.277] | +0.250 [+0.222, +0.279] | -0.126 [-0.148, -0.104] | +1.000 [+1.000, +1.000] |
| agent_hierarchical_memory | 900 | +0.250 [+0.222, +0.277] | +0.250 [+0.222, +0.279] | +0.000 [+0.000, +0.000] | +1.000 [+1.000, +1.000] |
| agent_no_memory | 900 | +0.502 [+0.470, +0.533] | +0.250 [+0.222, +0.279] | +0.000 [+0.000, +0.000] | +1.000 [+1.000, +1.000] |
| fixed_pipeline | 900 | +0.502 [+0.470, +0.533] | +0.250 [+0.222, +0.279] | +0.000 [+0.000, +0.000] | +1.000 [+1.000, +1.000] |

## Agent and recommendation diagnostics

| System | HR@5 | NDCG@5 | Useful clarification | Memory write accuracy | Stale-memory misuse | Mean turns | Mean tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| ablation_no_clarification | 1.000 [1.000, 1.000] | 0.977 [0.970, 0.982] | — | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 2.250 [2.221, 2.278] | 6.250 [6.111, 6.394] |
| ablation_no_recipient_isolation | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.916 [0.901, 0.930] | 0.000 [0.000, 0.000] | 2.250 [2.221, 2.278] | 5.617 [5.511, 5.728] |
| ablation_no_replanning | 0.877 [0.854, 0.899] | 0.877 [0.856, 0.897] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 2.127 [2.106, 2.149] | 5.000 [5.000, 5.000] |
| ablation_no_temporal_decay | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.127 [0.104, 0.149] | 2.377 [2.344, 2.408] | 6.250 [6.111, 6.400] |
| agent_flat_memory | 0.877 [0.854, 0.899] | 0.822 [0.800, 0.843] | — | 0.916 [0.901, 0.930] | 0.000 [0.000, 0.000] | 2.000 [2.000, 2.000] | 5.000 [5.000, 5.000] |
| agent_hierarchical_memory | 0.877 [0.854, 0.899] | 0.822 [0.800, 0.843] | — | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 2.000 [2.000, 2.000] | 5.000 [5.000, 5.000] |
| agent_no_memory | 0.751 [0.722, 0.780] | 0.618 [0.591, 0.645] | — | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 2.000 [2.000, 2.000] | 5.000 [5.000, 5.000] |
| fixed_pipeline | 0.751 [0.722, 0.780] | 0.618 [0.591, 0.645] | — | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 2.000 [2.000, 2.000] | 5.000 [5.000, 5.000] |
| full_agent | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 2.250 [2.221, 2.278] | 5.617 [5.511, 5.728] |

## Direct observations

- `task_success_rate`: full Agent 1.000 vs fixed pipeline 0.498 (absolute difference +0.502; higher is better).
- `hard_constraint_satisfaction_rate`: full Agent 1.000 vs fixed pipeline 0.750 (absolute difference +0.250; higher is better).
- `profile_contamination_rate`: full Agent 0.000 vs fixed pipeline 0.000 (absolute difference +0.000; lower is better).
- `recovery_success_rate`: full Agent 1.000 vs fixed pipeline 0.000 (absolute difference +1.000; higher is better).
- `ablation_no_clarification`: `task_success_rate` was 0.937 versus 1.000 for the full Agent (full minus ablation +0.063).
- `ablation_no_replanning`: `task_success_rate` was 0.877 versus 1.000 for the full Agent (full minus ablation +0.123).
- `ablation_no_recipient_isolation`: `profile_contamination_rate` was 0.126 versus 0.000 for the full Agent (full minus ablation -0.126).
- `ablation_no_temporal_decay`: `stale_memory_misuse_rate` was 0.127 versus 0.000 for the full Agent (full minus ablation -0.127).

These differences describe this frozen controlled benchmark. A confidence interval overlapping zero, or equal point estimates, is retained as a zero result rather than reframed as an improvement.

## Failure accounting

| System | Failure category | Count |
|---|---|---:|
| ablation_no_clarification | hard_constraint_violation | 57 |
| ablation_no_clarification | success | 843 |
| ablation_no_recipient_isolation | profile_contamination | 113 |
| ablation_no_recipient_isolation | success | 787 |
| ablation_no_replanning | hard_constraint_violation | 111 |
| ablation_no_replanning | success | 789 |
| ablation_no_temporal_decay | success | 900 |
| agent_flat_memory | hard_constraint_violation | 225 |
| agent_flat_memory | profile_contamination | 113 |
| agent_flat_memory | success | 562 |
| agent_hierarchical_memory | hard_constraint_violation | 225 |
| agent_hierarchical_memory | success | 675 |
| agent_no_memory | failed_recovery | 227 |
| agent_no_memory | hard_constraint_violation | 225 |
| agent_no_memory | success | 448 |
| fixed_pipeline | failed_recovery | 227 |
| fixed_pipeline | hard_constraint_violation | 225 |
| fixed_pipeline | success | 448 |
| full_agent | success | 900 |

### Deterministic failure examples

The list shows the lexicographically first saved example for each system/failure-category pair; the table above counts every failure.

- `ablation_no_clarification` / `ctrl-123-needs_clarification-000` / `needs_clarification`: hard_constraint_violation; final products=['H003', 'H001', 'H005', 'H002', 'H004']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:4202`.
- `ablation_no_recipient_isolation` / `ctrl-123-recipient_shift-000` / `recipient_shift`: profile_contamination; final products=['H004', 'H001', 'H006', 'H003', 'H005']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:4805`.
- `ablation_no_replanning` / `ctrl-123-rejection_recovery-000` / `rejection_recovery`: hard_constraint_violation; final products=['B006', 'B002', 'B001', 'B003', 'B007']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:4507`.
- `agent_flat_memory` / `ctrl-123-needs_clarification-000` / `needs_clarification`: hard_constraint_violation; final products=['H006', 'H003', 'H001', 'H005', 'H002']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:3302`.
- `agent_flat_memory` / `ctrl-123-recipient_shift-000` / `recipient_shift`: profile_contamination; final products=['H004', 'H001', 'H006', 'H003', 'H005']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:3305`.
- `agent_hierarchical_memory` / `ctrl-123-needs_clarification-000` / `needs_clarification`: hard_constraint_violation; final products=['H006', 'H003', 'H001', 'H005', 'H002']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:3602`.
- `agent_no_memory` / `ctrl-123-needs_clarification-000` / `needs_clarification`: hard_constraint_violation; final products=['H006', 'H003', 'H001', 'H005', 'H002']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:3002`.
- `agent_no_memory` / `ctrl-123-preference_alignment-000` / `preference_alignment`: failed_recovery; final products=['H001', 'H005', 'H002', 'H004', 'H007']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:3003`.
- `fixed_pipeline` / `ctrl-123-needs_clarification-000` / `needs_clarification`: hard_constraint_violation; final products=['H006', 'H003', 'H001', 'H005', 'H002']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:2702`.
- `fixed_pipeline` / `ctrl-123-preference_alignment-000` / `preference_alignment`: failed_recovery; final products=['H001', 'H005', 'H002', 'H004', 'H007']; source `results\raw\full\agentrec_full-a6c5235444e80f7b-20260825T094146-76f830\trajectories.jsonl:2703`.

## Reproduction

```powershell
python -m pytest -p no:cacheprovider
python -m agentrec.cli demo --scenario recipient_shift
python -m agentrec.experiments.run --config experiments/configs/smoke.yaml
python -m agentrec.experiments.run --config experiments/configs/pilot.yaml
python -m agentrec.experiments.run --config experiments/configs/full.yaml
python -m agentrec.reports.build --results results/raw --output reports/final_report.md
```

## Independently scoped extensions

The following runs use separate protocols and are not included in any controlled aggregate above.

### AgentRecBench Amazon real-log ranking

Run `agentrecbench_real_pilot-5e06aafcc42bea27-20260825T092126-4630a1` contains 400 saved records with `controlled=false`. Exact target@1 is a static ranking label, not interactive Agent task success.

| System | n | Exact target@1 | HR@3 | HR@5 | NDCG@5 |
|---|---:|---:|---:|---:|---:|
| candidate_order | 100 | 0.020 [0.000, 0.050] | 0.150 [0.080, 0.220] | 0.240 [0.150, 0.330] | 0.132 [0.087, 0.184] |
| popularity | 100 | 0.240 [0.160, 0.330] | 0.370 [0.270, 0.460] | 0.460 [0.350, 0.560] | 0.356 [0.276, 0.437] |
| full_history_lexical | 100 | 0.470 [0.380, 0.570] | 0.630 [0.530, 0.720] | 0.730 [0.630, 0.810] | 0.605 [0.530, 0.687] |
| short_term_recency | 100 | 0.450 [0.360, 0.550] | 0.670 [0.570, 0.760] | 0.790 [0.700, 0.870] | 0.628 [0.559, 0.705] |

Candidate-history leakage was found in the first smoke, fixed by excluding 99 candidate reviews, and the invalid run was retained. Full provenance, confidence intervals, and failures are in [the separate real-data report](real_data_report.md).

### Paid LLM controlled pilot

Run `agentrec_llm_pilot-22e15e5699fbfdf2-20260826T005917-66c9ac` requested model `gpt-5.5` and stopped with `completed` after saving 100 record(s). The configured run completed; its task metrics are reported in the saved run summary.

The current-provider ledger reports $7.83 settled. Across all provider ledgers, $7.98 is charged/reserved and $2.02 remains. Saved errors are redacted.

| n | Task success | Hard constraints | Profile contamination | Recovery success | Useful clarification | Mean tool calls |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.371 [0.229, 0.543] | 6.830 [6.530, 7.170] |

The 100 unfiltered pilot trajectories contain 1,451,090 input, 428,160 cached-input, and 35,919 output tokens; their OpenAI-price reference estimate totals $6.4063.

Negative mechanism signals are retained: 80 extra provider tool calls occurred across 80 task(s) despite `parallel_tool_calls=false` and were logged then suppressed to preserve one audited action per turn. Of 35 executed clarifications, 13 added information and 22 did not.

Representative audit records: extra-call example `ctrl-42-preference_alignment-000` at `results/raw/llm_pilot/agentrec_llm_pilot-22e15e5699fbfdf2-20260826T005917-66c9ac/trajectories.jsonl:2`; no-new-information clarification example `ctrl-42-recipient_shift-000` at `results/raw/llm_pilot/agentrec_llm_pilot-22e15e5699fbfdf2-20260826T005917-66c9ac/trajectories.jsonl:4`.

Cost basis: OpenAI public GPT-5.5 reference estimate; not an AgentRec gateway invoice. This is not the gateway's verified invoice price.


Raw trajectories, including failures, remain under `results/raw/`. Aggregated tables can always be regenerated from those records.
