[CmdletBinding()]
param(
    [string]$ClusterName = "mcp-local",
    [switch]$ForceKindRecreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptRoot "start-mcp.ps1"
$healthScript = Join-Path $scriptRoot "mcp-healthcheck.ps1"

if (-not (Test-Path $startScript)) {
    throw "Missing scripts/start-mcp.ps1. Verify repository checkout."
}

if (-not (Test-Path $healthScript)) {
    throw "Missing scripts/mcp-healthcheck.ps1. Verify repository checkout."
}

Write-Host "=== Bootstrapping MCP environment (cluster $ClusterName) ==="
& $startScript -ClusterName $ClusterName -ForceKindRecreate:$ForceKindRecreate

Write-Host "=== Running healthcheck ==="
& $healthScript

Write-Host "Bootstrap complete. Logs:"
Write-Host " - MCP run log: $env:TEMP\q-run.log"
Write-Host " - Q chat log:  $env:TEMP\qlog\qchat.log"

