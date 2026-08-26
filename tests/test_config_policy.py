from pathlib import Path

from agentrec.agent.policy import features_for_system
from agentrec.experiments.config import code_fingerprint, load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_configs_are_controlled_and_hash_stable(monkeypatch):
    monkeypatch.setenv("AGENTREC_MODEL", "gpt-5.5")
    for name in ("smoke.yaml", "pilot.yaml", "full.yaml"):
        path = PROJECT_ROOT / "experiments" / "configs" / name
        first, first_hash = load_config(str(path))
        second, second_hash = load_config(str(path))
        assert first == second
        assert first_hash == second_hash
        assert first["data"]["source"] == "controlled_catalog"
        assert first["agent"]["model"] == "offline-deterministic-policy"


def test_paid_api_configs_are_pinned_to_gpt_5_5(monkeypatch):
    monkeypatch.setenv("AGENTREC_BASE_URL", "http://gateway.example.test/v1")
    for name in ("llm_smoke.yaml", "llm_pilot.yaml"):
        config, _ = load_config(str(PROJECT_ROOT / "experiments" / "configs" / name))
        assert config["agent"]["model"] == "gpt-5.5"
        assert config["api"]["provider"] == "agentrec_gateway"
        assert config["api"]["base_url"] == "http://gateway.example.test/v1"
        assert config["api"]["api_key_env"] == "AGENTREC_API_KEY"
        assert config["api"]["insecure_http_ack_env"] == "AGENTREC_ALLOW_INSECURE_HTTP"
        assert config["api"]["pricing_reference_model"] == "gpt-5.5"


def test_each_ablation_changes_exactly_one_full_agent_feature():
    full = features_for_system("full_agent").to_dict()
    expected = {
        "ablation_no_clarification": "clarification",
        "ablation_no_replanning": "replanning",
        "ablation_no_recipient_isolation": "recipient_isolation",
        "ablation_no_temporal_decay": "temporal_decay",
    }
    for system, changed_key in expected.items():
        ablated = features_for_system(system).to_dict()
        differences = [key for key in full if full[key] != ablated[key]]
        assert differences == [changed_key]


def test_code_fingerprint_is_stable_and_nonempty():
    assert code_fingerprint(PROJECT_ROOT) == code_fingerprint(PROJECT_ROOT)
    assert len(code_fingerprint(PROJECT_ROOT)) == 16
