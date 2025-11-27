[CmdletBinding()]
param(
    [string]$ClusterName = "mcp-local",
    [switch]$ForceKindRecreate,
    [string]$HealthEndpoint = "http://127.0.0.1:8000/healthz"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param(
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )

    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] $Message" -ForegroundColor $Color
}

function Ensure-Directory {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Ensure-LocalBin {
    $localBin = Join-Path $env:USERPROFILE ".local\bin"
    Ensure-Directory -Path $localBin

    $pathParts = $env:PATH -split ';'
    if ($pathParts -notcontains $localBin) {
        $env:PATH = "$localBin;$($env:PATH)"
    }

    return $localBin
}

function Install-Uv {
    Write-Step "Attempting to install uv (uvx) via Python pip."
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        $python = Get-Command py -ErrorAction SilentlyContinue
    }

    if (-not $python) {
        throw "Python runtime not found. Install Python 3.11+ so uvx can be installed."
    }

    & $python.Source -m pip install --user uv | Out-Null
}

function Ensure-Uvx {
    if (Get-Command uvx -ErrorAction SilentlyContinue) {
        return
    }

    Install-Uv

    if (-not (Get-Command uvx -ErrorAction SilentlyContinue)) {
        throw "uvx is still missing after installation attempt."
    }
}

function Get-StableKubernetesVersion {
    $fallback = "v1.29.2"
    try {
        $stable = (Invoke-RestMethod -Uri "https://dl.k8s.io/release/stable.txt" -UseBasicParsing).Trim()
        if ([string]::IsNullOrWhiteSpace($stable)) {
            return $fallback
        }
        return $stable
    } catch {
        Write-Step "Falling back to $fallback for kubectl download." -Color [ConsoleColor]::Yellow
        return $fallback
    }
}

function Ensure-Kubectl {
    param([string]$LocalBin)

    if (Get-Command kubectl -ErrorAction SilentlyContinue) {
        return
    }

    $version = Get-StableKubernetesVersion
    $url = "https://dl.k8s.io/release/$version/bin/windows/amd64/kubectl.exe"
    $dest = Join-Path $LocalBin "kubectl.exe"

    Write-Step "kubectl not found. Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Step "kubectl installed to $dest"
}

function Ensure-Kind {
    param([string]$LocalBin)

    if (Get-Command kind -ErrorAction SilentlyContinue) {
        return
    }

    $version = "v0.23.0"
    $url = "https://kind.sigs.k8s.io/dl/$version/kind-windows-amd64"
    $dest = Join-Path $LocalBin "kind.exe"

    Write-Step "kind not found. Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Step "kind installed to $dest"
}

function Ensure-DockerRunning {
    $dockerProcess = Get-Process -Name "Docker Desktop","com.docker.backend","dockerd" -ErrorAction SilentlyContinue
    if (-not $dockerProcess) {
        throw "Docker Desktop must be running to provision a kind cluster."
    }
}

function Try-CopyAwsKubeconfig {
    param([string]$Destination)

    $awsDir = Join-Path $env:USERPROFILE ".aws"
    if (-not (Test-Path $awsDir)) {
        return $false
    }

    $candidate = Get-ChildItem -Path $awsDir -Filter "kubeconfig*" -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $candidate) {
        return $false
    }

    Copy-Item -Path $candidate.FullName -Destination $Destination -Force
    Write-Step "Copied kubeconfig from $($candidate.FullName) to $Destination"
    return $true
}

function Ensure-Kubeconfig {
    param(
        [string]$ClusterName,
        [string]$LocalBin,
        [switch]$ForceKindRecreate
    )

    $kubeDir = Join-Path $env:USERPROFILE ".kube"
    Ensure-Directory -Path $kubeDir
    $kubeconfig = Join-Path $kubeDir "config"

    if (Test-Path $kubeconfig -PathType Leaf -and -not $ForceKindRecreate) {
        Write-Step "Found existing kubeconfig at $kubeconfig"
        return $kubeconfig
    }

    if (Try-CopyAwsKubeconfig -Destination $kubeconfig) {
        return $kubeconfig
    }

    Write-Step "No kubeconfig found. Creating kind cluster '$ClusterName'."
    Ensure-Kind -LocalBin $LocalBin
    Ensure-DockerRunning

    $existingClusters = try { & kind get clusters 2>$null } catch { @() }
    $clusterExists = $existingClusters -contains $ClusterName

    if ($clusterExists -and $ForceKindRecreate) {
        Write-Step "Deleting existing kind cluster '$ClusterName' because -ForceKindRecreate was provided."
        & kind delete cluster --name $ClusterName | Out-Null
        $clusterExists = $false
    }

    if (-not $clusterExists) {
        & kind create cluster --name $ClusterName --wait 120s
        if ($LASTEXITCODE -ne 0) {
            throw "kind create cluster failed (exit code $LASTEXITCODE)."
        }
    } else {
        Write-Step "kind cluster '$ClusterName' already exists. Skipping creation."
    }

    if (-not (Test-Path $kubeconfig -PathType Leaf)) {
        throw "kubeconfig was not created at $kubeconfig"
    }

    return $kubeconfig
}

function Publish-McpConfig {
    param([string]$KubeconfigPath)

    $templatePath = Join-Path $PSScriptRoot "..\deploy\mcp.json"
    if (-not (Test-Path $templatePath)) {
        throw "Template mcp.json not found at $templatePath"
    }

    $jsonText = Get-Content -Path $templatePath -Raw
    $escapedPath = $KubeconfigPath -replace '\\', '\\\\'
    $jsonText = $jsonText -replace '\{\{KUBECONFIG_PATH\}\}', $escapedPath

    $targetDir = Join-Path $env:USERPROFILE ".aws\amazonq"
    Ensure-Directory -Path $targetDir
    $targetPath = Join-Path $targetDir "mcp.json"
    Set-Content -Path $targetPath -Value $jsonText -Encoding utf8
    Write-Step "Wrote MCP config to $targetPath"
    return $targetPath
}

function Get-McpProcess {
    try {
        return Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and $_.CommandLine -match "kubernetes-mcp-server"
        }
    } catch {
        return @()
    }
}

function Start-McpServer {
    param(
        [string]$KubeconfigPath,
        [string]$HealthEndpoint
    )

    $existing = Get-McpProcess
    if ($existing) {
        $pids = ($existing | Select-Object -ExpandProperty ProcessId) -join ', '
        Write-Step "kubernetes-mcp-server already running (PID(s): $pids)"
        return
    }

    $uvx = (Get-Command uvx).Source
    $runLog = Join-Path $env:TEMP "q-run.log"
    $null = New-Item -ItemType File -Path $runLog -Force

    $arguments = @(
        "kubernetes-mcp-server@latest",
        "--kubeconfig", $KubeconfigPath,
        "--addr", "127.0.0.1:8000"
    )

    Write-Step "Starting kubernetes-mcp-server via uvx. Logs -> $runLog"
    Start-Process -FilePath $uvx -ArgumentList $arguments -RedirectStandardOutput $runLog -RedirectStandardError $runLog -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $HealthEndpoint -TimeoutSec 2
            if ($response) {
                Write-Step "MCP health endpoint responded: $($response | ConvertTo-Json -Compress)"
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    Write-Warning "MCP health endpoint $HealthEndpoint not reachable yet. Continuing."
}

function Start-QLauncher {
    $chatDir = Join-Path $env:TEMP "qlog"
    Ensure-Directory -Path $chatDir
    $chatLog = Join-Path $chatDir "qchat.log"

    $qCmd = Get-Command q -ErrorAction SilentlyContinue
    if (-not $qCmd) {
        "q launcher not present on PATH. $(Get-Date -Format o)" | Out-File -FilePath $chatLog -Encoding utf8
        Write-Step "q launcher not installed; wrote placeholder log at $chatLog" -Color [ConsoleColor]::Yellow
        return
    }

    $existing = Get-Process -Name "q" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Step "q launcher already running (PID $($existing.Id))."
        return
    }

    Start-Process -FilePath $qCmd.Source -ArgumentList @() -RedirectStandardOutput $chatLog -RedirectStandardError $chatLog -Environment @{ Q_LOG_LEVEL = "trace" } -WindowStyle Hidden | Out-Null
    Write-Step "Started q launcher. Logs -> $chatLog"
}

function Invoke-KubectlCheck {
    param(
        [string[]]$Arguments,
        [string]$Description
    )

    Write-Step "kubectl $Description"
    $output = & kubectl @Arguments 2>&1
    $output | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl $Description failed with exit code $LASTEXITCODE"
    }
}

$localBin = Ensure-LocalBin
Ensure-Uvx
Ensure-Kubectl -LocalBin $localBin
$kubeconfig = Ensure-Kubeconfig -ClusterName $ClusterName -LocalBin $localBin -ForceKindRecreate:$ForceKindRecreate
Publish-McpConfig -KubeconfigPath $kubeconfig | Out-Null
Start-McpServer -KubeconfigPath $kubeconfig -HealthEndpoint $HealthEndpoint
Start-QLauncher

$env:KUBECONFIG = $kubeconfig
Invoke-KubectlCheck -Arguments @("cluster-info") -Description "cluster-info"
Invoke-KubectlCheck -Arguments @("get", "nodes", "-o", "wide") -Description "get nodes"

Write-Step "MCP startup completed successfully." -Color [ConsoleColor]::Green

