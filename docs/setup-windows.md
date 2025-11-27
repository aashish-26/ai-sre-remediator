# Windows Bootstrap Guide

These steps install all required tooling, ensure a local kubeconfig exists, and start the MCP server plus the Amazon Q launcher on Windows 10/11.

## Prerequisites

- PowerShell 7+ running as your normal user (no elevation required).
- Docker Desktop running (for kind-based clusters when no kubeconfig exists).
- Internet access to download `kubectl`, `kind`, and `uvx` on first run.

## One-click bootstrap

From the repository root run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap-and-run.ps1
```

The script is idempotent. It will:

1. Install/upgrade `uvx`, `kubectl`, and `kind` into `%USERPROFILE%\.local\bin` when missing.
2. Ensure `%USERPROFILE%\.kube\config` exists by copying an AWS-provided kubeconfig or by creating a local kind cluster named `mcp-local`.
3. Publish `deploy/mcp.json` to `%USERPROFILE%\.aws\amazonq\mcp.json` with the correct Windows kubeconfig path.
4. Launch `kubernetes-mcp-server` via `uvx`, start the Amazon Q launcher when available, and stream logs to `%TEMP%\q-run.log` plus `%TEMP%\qlog\qchat.log`.
5. Validate `kubectl cluster-info` and `kubectl get nodes` so the MCP server only starts when the cluster is reachable.

## Verifying the environment

After the bootstrap completes:

- Review `%TEMP%\q-run.log` for MCP server output and `%TEMP%\qlog\qchat.log` for Q launcher activity.
- Re-run the healthcheck any time with `pwsh -File scripts\mcp-healthcheck.ps1`.
- Delete/recreate the local kind cluster with `powershell -ExecutionPolicy Bypass -File scripts\bootstrap-and-run.ps1 -ForceKindRecreate` when you need a clean slate.

