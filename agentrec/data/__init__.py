"""External-data adapters kept separate from controlled fixtures."""

from agentrec.data.agentrecbench import (
    AGENTRECBENCH_DATASET_ID,
    AGENTRECBENCH_REVISION,
    AgentRecBenchSubset,
    RealRecommendationTask,
    build_processed_subset,
    load_processed_subset,
)

__all__ = [
    "AGENTRECBENCH_DATASET_ID",
    "AGENTRECBENCH_REVISION",
    "AgentRecBenchSubset",
    "RealRecommendationTask",
    "build_processed_subset",
    "load_processed_subset",
]
