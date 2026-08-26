"""Experiment-system feature isolation.

The mapping below is the executable definition of each baseline/ablation.  Keeping
it outside prompts prevents accidental multi-feature ablations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class AgentFeatures:
    autonomous_planning: bool
    memory_mode: str
    clarification: bool
    replanning: bool
    recipient_isolation: bool = True
    temporal_decay: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


SYSTEM_FEATURES = {
    "fixed_pipeline": AgentFeatures(False, "none", False, False),
    "agent_no_memory": AgentFeatures(True, "none", False, False),
    "agent_flat_memory": AgentFeatures(True, "flat", False, False, recipient_isolation=False),
    "agent_hierarchical_memory": AgentFeatures(True, "hierarchical", False, False),
    "full_agent": AgentFeatures(True, "hierarchical", True, True),
    "ablation_no_clarification": AgentFeatures(True, "hierarchical", False, True),
    "ablation_no_replanning": AgentFeatures(True, "hierarchical", True, False),
    "ablation_no_recipient_isolation": AgentFeatures(
        True, "hierarchical", True, True, recipient_isolation=False
    ),
    "ablation_no_temporal_decay": AgentFeatures(
        True, "hierarchical", True, True, temporal_decay=False
    ),
}


def features_for_system(system: str) -> AgentFeatures:
    try:
        return SYSTEM_FEATURES[system]
    except KeyError as exc:
        raise ValueError(f"unknown experiment system: {system}") from exc

