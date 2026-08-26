param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [string]$Model = "gpt-5.5",
    [decimal]$MaxCostUsd = 10.00,
    [switch]$AllowInsecureHttp
)

$ErrorActionPreference = "Stop"
$AgentRecKeyName = "AGENTREC_API_KEY"
$AgentRecAckName = "AGENTREC_ALLOW_INSECURE_HTTP"

if ($MaxCostUsd -le 0) {
    throw "MaxCostUsd must be greater than zero."
}

$AgentRecUri = [Uri]$BaseUrl
if ($AgentRecUri.Scheme -notin @("http", "https")) {
    throw "BaseUrl must use http or https."
}
if ($AgentRecUri.Scheme -eq "http" -and -not $AllowInsecureHttp) {
    throw "This endpoint uses plaintext HTTP. Re-run with -AllowInsecureHttp only if you accept interception risk."
}

$AgentRecSecret = Read-Host "Paste $AgentRecKeyName (input is hidden)" -AsSecureString
$AgentRecPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($AgentRecSecret)

try {
    $AgentRecPlaintext = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($AgentRecPointer)
    if ([string]::IsNullOrWhiteSpace($AgentRecPlaintext)) {
        throw "$AgentRecKeyName cannot be empty."
    }

    [Environment]::SetEnvironmentVariable($AgentRecKeyName, $AgentRecPlaintext, "User")
    [Environment]::SetEnvironmentVariable("AGENTREC_PROVIDER", "agentrec_gateway", "User")
    [Environment]::SetEnvironmentVariable("AGENTREC_BASE_URL", $AgentRecUri.AbsoluteUri.TrimEnd('/'), "User")
    [Environment]::SetEnvironmentVariable("AGENTREC_MODEL", $Model, "User")
    [Environment]::SetEnvironmentVariable(
        "AGENTREC_MAX_COST_USD",
        $MaxCostUsd.ToString([Globalization.CultureInfo]::InvariantCulture),
        "User"
    )
    $AgentRecAck = if ($AgentRecUri.Scheme -eq "http") { "I_ACCEPT_PLAINTEXT_HTTP" } else { $null }
    [Environment]::SetEnvironmentVariable($AgentRecAckName, $AgentRecAck, "User")
}
finally {
    if ($AgentRecPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($AgentRecPointer)
    }
    Remove-Variable AgentRecPlaintext, AgentRecSecret, AgentRecPointer -ErrorAction SilentlyContinue
}

Write-Host "Configured $AgentRecKeyName without echoing it."
Write-Host "AGENTREC_PROVIDER=agentrec_gateway"
Write-Host "AGENTREC_BASE_URL=$($AgentRecUri.AbsoluteUri.TrimEnd('/'))"
Write-Host "AGENTREC_MODEL=$Model"
Write-Host "AGENTREC_MAX_COST_USD=$MaxCostUsd"
Write-Host "Completely restart Codex, reopen this task, and reply: restarted"
