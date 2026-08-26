# AgentRec working instructions

Read `HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, and `docs/EXPERIMENT_PROTOCOL.md` before implementation.

The user authorized implementation and local experiment execution in this project, including downloading public datasets and installing project-scoped dependencies when approvals permit. Do not publish, deploy, purchase products, or send external messages.

Keep recommendation as the environment and tool layer; the main system under study is the Agent loop: planning, clarification, tool choice, memory update, reflection, and replanning.

Preserve `upstream/bearcode/` as a readable source snapshot. Prefer new code under `agentrec/` plus narrow, tested upstream patches only when integration requires them. Never copy `.env`, API keys, local virtual environments, caches, or machine-specific absolute paths into tracked files.

Do not fabricate results. Save raw per-task trajectories before aggregation, keep failed runs, record config and code versions, and distinguish controlled tasks from real logged data. Treat null and negative results as valid findings.

Run the pilot before the full matrix. Do not expand scope to large-model training, reinforcement learning, production deployment, or online A/B testing unless the user explicitly asks.
