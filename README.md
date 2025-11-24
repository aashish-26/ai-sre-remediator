# AI-Driven Kubernetes Auto-Remediation Platform (ai-sre-remediator)

One-line summary
-----------------

Kubernetes operator + MCP-backed reasoning that ingests alerts/events, proposes safe remediation from a whitelist of templates, and (optionally) executes approved actions — fully auditable and GitOps-friendly.

## Table of contents

- [Goals](#goals)
- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [Internals & Components](#internals--components)
- [CRD & Prompt Schema](#crd--prompt-schema)
- [Security & Safety](#security--safety)
- [Development](#development)
- [CI / Tests](#ci--tests)
- [Contributing](#contributing)

## Goals

- Prototype an operator (Python + `kopf`) that reasons about incidents via an MCP client and suggests constrained remediations.
- Provide a demo flow (simulate alert → operator recommends → dry-run / apply) suitable for minikube.
- Be auditable and GitOps-friendly: every recommended decision is logged and can be committed to a repo for traceability.

## Architecture

High level flow:

- Event source (Prometheus Alertmanager, K8s Events, or simulated webhook) → Operator
- Operator collects context (recent logs, pod spec, metrics snapshot)
- Operator calls MCP (Model Context Protocol) with a strict prompt template and JSON schema
- MCP returns a constrained JSON recommendation (template id, command, confidence)
- Validator checks recommendation against a signed template registry
- Executor runs in dry-run or apply mode (RBAC-limited) and emits audit artifacts (logs, git commit, or issue)
- Observability collects metrics and traces for operator actions

Mermaid diagram (rendered in supported viewers):

```mermaid
flowchart LR
  A[Event Source\n(Alertmanager, K8s Events, Webhook)] --> B[Operator]
  B --> C[Context Builder\n(logs, pod spec, metrics)]
  C --> D[MCP Client\n(strict prompt, schema)]
  D --> E[Decision Validator\n(whitelist + signatures)]
  E --> F[Executor\n(dry-run / apply)]
  F --> G[Audit & GitOps\n(logs, commits, issues)]
  F --> H[Observability\n(prometheus, grafana, loki)]
```

## Quickstart

Prerequisites:

- `minikube` (or a Kubernetes cluster)
- `kubectl` configured
- Python 3.11+ recommended

Windows PowerShell (developer local run):

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
minikube start --driver=docker
kubectl apply -f demos/crashloop-pod.yaml
python operator/operator.py
kubectl apply -f demos/simulated-alert.yaml
```

macOS / Linux (bash):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
minikube start --driver=docker
kubectl apply -f demos/crashloop-pod.yaml
python operator/operator.py
```

## Internals & Components

- **Operator (`operator/`)**: kopf-based controller that watches alerts/CRs and orchestrates the remediation flow.
  - `operator/operator.py` — controller entrypoint for local testing
  - `operator/pkg/` — operator helpers (MCP client wrapper, validator, executor, template registry)
- **API (`api/v1/`)**: CRD YAMLs for `IncidentRemediation` (used for simulated alerts and operator-driven decisions).
- **Templates (`templates/`)**: Pre-approved remediation templates (YAML) with metadata (id, risk level, params).
- **Validator**: Ensures MCP response maps to an allowed template id and parameters are within policy; verifies signatures if present.
- **Executor**: Two modes — `dry-run` (prints the actions) and `apply` (performs K8s API calls using the operator's service account).
- **Audit & GitOps**: Each decision can be recorded by committing a short JSON/YAML file to a tracked repo or by writing to an audit log store.
- **Observability**: Operator exposes Prometheus metrics; use Grafana/Loki/Jaeger to visualize and trace decisions.

## CRD & Prompt Schema

Operator expects MCP to return a single JSON object matching this schema (example):

```json
{
  "action": "restart-pod",
  "template_id": "restart-pod-v1",
  "command": "kubectl delete pod <pod-name> -n <ns>",
  "confidence": 0.93,
  "rationale": "Container image pull failed repeatedly; restarting should recover pod."
}
```

The in-repo CRD (simplified) is available at `api/v1/incidentremediation_crd.yaml` and should be used for simulated alerts.

## Security & Safety

- Never send secrets or raw tokens to MCP. Always redact and only send minimal context.
- Templates must be whitelisted; the operator refuses arbitrary shell execution.
- Default behavior: `dry-run`. `apply` requires explicit approval and a confidence threshold + signed template.
- Least privilege: the operator service account should only have verbs required for the whitelisted templates.

## Development

- Create and activate a virtualenv, then install requirements:

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- Run unit tests:

```powershell
pytest -q
```

- Useful files:
  - `operator/requirements.txt` — operator-specific runtime deps
  - `templates/` — remediation templates and `templates/schema.json` (template schema)

## CI / Tests

- CI pipeline (`.github/workflows/ci.yml`) will run lint, unit tests, and optionally an integration job that uses a minikube runner.

## Contributing

- Work on `feature/<short>` branches and open PRs to `main`.
- Template changes require code review and at least two approvers (or signed commits) because they affect safety and RBAC.

---

If you'd like, I can also:

- Add a rendered `templates/schema.json` and a few example remediation templates.
- Fill `operator/operator.py` with a minimal kopf skeleton that registers handlers for simulated alerts.
- Create a `requirements-dev.txt` and pin exact versions.

Tell me which of the above you'd like next.