param(
    [ValidateSet("sribd", "openai")]
    [string]$Provider = "sribd",
    [string]$Model = "codex.gpt-5.5",
    [decimal]$MaxCostUsd = 10.00
)

$ErrorActionPreference = "Stop"

if ($MaxCostUsd -le 0) {
    throw "MaxCostUsd must be greater than zero."
}

$AgentRecKeyName = if ($Provider -eq "sribd") { "SRIBD_API_KEY" } else { "OPENAI_API_KEY" }
$AgentRecSecret = Read-Host "Paste $AgentRecKeyName (input is hidden)" -AsSecureString
$AgentRecPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($AgentRecSecret)

try {
    $AgentRecPlaintext = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($AgentRecPointer)
    if ([string]::IsNullOrWhiteSpace($AgentRecPlaintext)) {
        throw "$AgentRecKeyName cannot be empty."
    }

    [Environment]::SetEnvironmentVariable($AgentRecKeyName, $AgentRecPlaintext, "User")
    [Environment]::SetEnvironmentVariable("AGENTREC_PROVIDER", $Provider, "User")
    [Environment]::SetEnvironmentVariable("AGENTREC_MODEL", $Model, "User")
    [Environment]::SetEnvironmentVariable(
        "AGENTREC_MAX_COST_USD",
        $MaxCostUsd.ToString([Globalization.CultureInfo]::InvariantCulture),
        "User"
    )
}
finally {
    if ($AgentRecPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($AgentRecPointer)
    }
    Remove-Variable AgentRecPlaintext, AgentRecSecret, AgentRecPointer -ErrorAction SilentlyContinue
}

Write-Host "Configured $AgentRecKeyName without echoing it."
Write-Host "AGENTREC_PROVIDER=$Provider"
Write-Host "AGENTREC_MODEL=$Model"
Write-Host "AGENTREC_MAX_COST_USD=$MaxCostUsd"
Write-Host "Completely restart Codex, reopen this task, and reply: restarted"
