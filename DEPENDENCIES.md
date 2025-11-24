System & CLI tools

Docker (desktop or engine)

minikube (latest stable)

kubectl (matching your cluster)

helm (v3+)

git, gh (GitHub CLI optional)

jq, yq (JSON/YAML CLI tools)

make (optional, for Makefile tasks)

Docker images (base)

python:3.11-slim (operator prototype)

golang:1.20 (optional build)

ghcr.io/kubernetes-helm/tiller is not needed; use standard Helm.

Observability images will be installed via Helm charts (Prometheus, Grafana, Loki, Jaeger).

Helm / chart dependencies (examples for charts/requirements.yaml)

prometheus-community/kube-prometheus-stack

grafana/grafana (or included in stack)

grafana/loki / grafana/promtail

observability (jaeger) chart

Dev tools (VS Code extensions)

Kubernetes (Azure / Red Hat) extension

YAML + schema validation

Python extension (if using Python)

GitLens

Docker extension