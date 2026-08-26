param()

$ErrorActionPreference = "Stop"
$AgentRecRoot = Split-Path -Parent $PSScriptRoot

Push-Location -LiteralPath $AgentRecRoot
try {
    python -m pytest -p no:cacheprovider
    python -m agentrec.cli demo --scenario recipient_shift
    python -m agentrec.cli demo --scenario rejection_recovery
    python -m agentrec.experiments.run --config experiments/configs/smoke.yaml
    python -m agentrec.experiments.run --config experiments/configs/pilot.yaml
    python -m agentrec.experiments.run --config experiments/configs/full.yaml
    python -m agentrec.reports.build --results results/raw --output reports/final_report.md
}
finally {
    Pop-Location
}
