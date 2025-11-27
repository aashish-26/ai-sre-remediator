[CmdletBinding()]
param(
    [string]$HealthEndpoint = "http://127.0.0.1:8000/healthz",
    [switch]$SkipProcessCheck,
    [switch]$AllowDryRunOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param(
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )
    Write-Host "[HEALTHCHECK] $Message" -ForegroundColor $Color
}

function Assert-Success {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

if (-not $SkipProcessCheck) {
    $processMatches = @()
    try {
        $processMatches = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and $_.CommandLine -match "kubernetes-mcp-server"
        }
    } catch {
        $processMatches = Get-Process -Name "kubernetes-mcp-server","uvx" -ErrorAction SilentlyContinue
    }

    Assert-Success -Condition ($processMatches.Count -gt 0) -Message "kubernetes-mcp-server process not detected. Pass -SkipProcessCheck if you intentionally ran a dry-run."
    Write-Step "Detected running kubernetes-mcp-server process."
} elseif (-not $AllowDryRunOnly) {
    Write-Step "Process check skipped by request." -Color [ConsoleColor]::Yellow
}

$healthOk = $false
try {
    $response = Invoke-RestMethod -Uri $HealthEndpoint -TimeoutSec 5
    if ($response -and $response.status -eq "ok") {
        $healthOk = $true
        Write-Step "Health endpoint returned status=ok."
    } else {
        Write-Step "Health endpoint returned unexpected payload: $($response | ConvertTo-Json -Compress)" -Color [ConsoleColor]::Yellow
    }
} catch {
    Write-Step "Health endpoint $HealthEndpoint is not reachable: $($_.Exception.Message)" -Color [ConsoleColor]::Yellow
}

if (-not $healthOk) {
    Write-Step "Falling back to kubectl smoke tests + uvx presence." -Color [ConsoleColor]::Yellow
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        throw "kubectl not found on PATH."
    }

    $clusterInfo = & kubectl cluster-info 2>&1
    $clusterInfo | ForEach-Object { Write-Host $_ }
    Assert-Success -Condition ($LASTEXITCODE -eq 0) -Message "kubectl cluster-info failed."

    $nodes = & kubectl get nodes -o wide 2>&1
    $nodes | ForEach-Object { Write-Host $_ }
    Assert-Success -Condition ($LASTEXITCODE -eq 0) -Message "kubectl get nodes failed."

    if (-not $AllowDryRunOnly) {
        $uvxProcess = Get-Process -Name "uvx" -ErrorAction SilentlyContinue
        Assert-Success -Condition ($uvxProcess) -Message "uvx process not running while MCP should be active."
    }
}

Write-Step "MCP healthcheck passed." -Color [ConsoleColor]::Green

