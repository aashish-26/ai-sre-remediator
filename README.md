Project name

AI-Driven Kubernetes Auto-Remediation Platform (ai-sre-remediator)

One-line summary

Kubernetes operator + MCP-backed reasoning that ingests alerts/events, proposes safe remediation from a whitelist of templates, and (optionally) executes approved actions — fully auditable and GitOps-friendly.

Goals

Learn Kubernetes internals, Operators, GitOps, observability, and SRE practices by building a production-ish system end-to-end.

Integrate MCP (Model Context Protocol) / LLM reasoning securely to convert cluster context into constrained remediation recommendations.

Ship a demonstrable repo: deploy to minikube, simulate incidents, see recommendations, apply safe fixes, and produce auditable postmortems.

Scope & non-goals

In scope

Prototype operator (Python/kopf for speed; Go/controller-runtime optional later).

Prometheus + Alertmanager + Grafana + Loki + Jaeger for observability.

MCP client with strict prompt templates and schema-validated responses.

Whitelisted remediation templates and a dry-run executor, plus approval flow.

CI pipeline that builds and deploys to minikube and runs integration tests.

Out of scope (for initial delivery)

Multi-cluster production rollouts, complex RBAC cross-account plumbing, or hosted LLM infra beyond your lab/dev MCP instances. These can be added later.

Architecture (short)

Event sources: Prometheus alerts, Kubernetes Events, Webhooks (simulated alerts).

Operator (in-cluster controller): Watches alerts/CRs/events; builds context (recent logs, pod spec, metrics summary); calls MCP with constrained prompt; receives JSON recommendation.

Decision validator: Validates recommendation against a signed, versioned whitelist of templates.

Executor: Dry-run mode prints command; apply mode executes templated kubectl/K8s API calls with RBAC-limited service account.

Audit & GitOps: Each decision written to logs + commit/issue in a repo for traceability.

Observability: Prometheus metrics, Grafana dashboard, Loki logs, Jaeger traces.

Human interface: Slack bot / web UI / CLI for approvals and visibility.

Quickstart (developer, first 10 minutes)

minikube start --driver=docker

git clone <your-repo> → cd ai-sre-remediator

Create and apply demo crashloop pod:

kubectl apply -f demos/crashloop-pod.yaml


Run the prototype operator (local) to confirm you see pod events:

source venv/bin/activate
python operator.py

Security & safety rules (must follow)

Never send raw secrets or tokens to MCP. Strip and redact.

Templates → only preapproved, parameterized actions. No arbitrary shell.

Default to dry-run. Apply only via approval or strict policy (signature + confidence threshold).

Least privilege: operator service account must only have the smallest set of verbs/resources.

Audit trail: trace-id, prompt hash, MCP response, template id, executor outcome — commit or append to durable store.

Deliverables (what this repo will contain)

operator/ — controller code (initially Python kopf).

templates/ — remediation templates (YAML) with IDs and risk levels.

pkg/mcp/ — client for MCP server.

demos/ — sample failing apps + simulation scripts.

manifests/ — RBAC, Deployment, CRD (IncidentRemediation).

.github/workflows/ci.yml — builds, tests, deploy to minikube.

docs/ — architecture, runbook, security, demo steps.

charts/ — Helm chart for operator.

test/ — integration and chaos test scripts.

How to demo (short script)
# start minikube
minikube start --driver=docker

# create demo crashloop pod
kubectl apply -f demos/crashloop-pod.yaml

# run operator locally (will log recommendations)
source venv/bin/activate
python operator.py

# simulate an alert (if you use SimulatedAlert CRD)
kubectl apply -f demos/simulated-alert.yaml

Contributing / workflow

Work on feature branches: feature/<short>; PRs required to merge to main.

Templates only change via PR and require signed commit or 2 approvers.

CI runs unit tests, lint, and minikube integration tests.

Useful references (internal)

CRD: api/v1/incidentremediation_types.go (or YAML for Python).

Prompt templates: prompts/remediation_prompt.json.tpl.

Template registry: templates/ (include schema file templates/schema.json).

Appendix: example prompt schema (MUST use)

MCP request should ask for a single JSON response matching this schema:

{
  "action": "string (one of allowed template ids)",
  "template_id": "string",
  "command": "string (kubectl or k8s patch snippet)",
  "confidence": "number 0.0-1.0",
  "rationale": "string < 60 words"
}