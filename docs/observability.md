**Observability & Prometheus Alerting**

- **Purpose**: Install Prometheus stack and wire Alertmanager to deliver CrashLoopBackOff alerts to the operator's simulated alert flow via a webhook receiver.

Setup steps
 - **Add Helm repo and install kube-prometheus-stack** (creates Prometheus, Alertmanager, Grafana):

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack --namespace monitoring --create-namespace
```

Manifests added to this repo
- `manifests/monitoring/prometheusrule-crashloop.yaml` — PrometheusRule that fires `PodCrashLooping` when pods report `CrashLoopBackOff` (for >1m).
- `manifests/monitoring/alertmanagerconfig-webhook.yaml` — an `AlertmanagerConfig` which routes alerts to the `ai-sre-webhook` receiver using a webhook to `http://alert-receiver.monitoring.svc.cluster.local:5000/alert`.
- `manifests/monitoring/webhook-receiver-deployment.yaml` — a simple Deployment + Service + ConfigMap which runs `alertmanager_webhook_receiver.py` (Flask) and exposes it in the `monitoring` namespace as `alert-receiver:5000`.
- `scripts/alertmanager_webhook_receiver.py` — the same receiver script for local runs (useful if you prefer to run locally instead of in-cluster).

How the webhook works
- The webhook expects Alertmanager webhook JSON (the default Alertmanager webhook format). For each alert it:
  - extracts `namespace` and `pod` from alert labels (falls back to `default`/`unknown-pod`),
  - builds a `context` similar to the operator's event context,
  - calls `ai_operator.pkg.mcp_client.query_mcp` and the validation/executor pipeline the same way the operator does, generating an audit entry when a template is selected.

Deploy in-cluster (recommended test path)
1. Install the Prometheus stack (see helm commands above).
2. Apply the webhook receiver and AlertmanagerConfig:

```powershell
kubectl apply -f manifests/monitoring/webhook-receiver-deployment.yaml
kubectl apply -f manifests/monitoring/alertmanagerconfig-webhook.yaml
kubectl apply -f manifests/monitoring/prometheusrule-crashloop.yaml
```

3. Ensure the `alert-receiver` Service is routable from the Alertmanager pod in the `monitoring` namespace. The `AlertmanagerConfig` points to `alert-receiver.monitoring.svc.cluster.local:5000`.

Local test (no cluster deployment)
- Run the webhook receiver locally and POST a sample Alertmanager webhook to it.

```powershell
# from repo root
python .\scripts\alertmanager_webhook_receiver.py

# then POST a sample payload (PowerShell example)
$payload = @'
{
  "receiver": "ai-sre-webhook",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {"alertname": "PodCrashLooping", "namespace": "default", "pod": "demo-crashpod"},
      "annotations": {"description": "Simulated CrashLoopBackOff for demo-crashpod"}
    }
  ]
}
'@

Invoke-RestMethod -Uri http://localhost:5000/alert -Method POST -Body $payload -ContentType 'application/json'
```

Verifying alerts in Grafana/Alertmanager
- Access Grafana: after installation, get admin password and port-forward to access Grafana or configure Ingress. See kube-prometheus-stack docs.
- Access Alertmanager UI: `kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093` (service name may vary with chart values) then open `http://localhost:9093`.

Notes and caveats
- The `AlertmanagerConfig` CRD is provided by the Prometheus Operator. If your installation prefers editing Alertmanager config directly (secret named `alertmanager-main`), you can instead edit it via Helm values or by creating the appropriate Secret.
- The webhook receiver in this repo runs the operator simulation code directly. For production, replace the receiver with a small service that creates an `IncidentRemediation` CRD or posts to the operator API.
- The Deployment in `webhook-receiver-deployment.yaml` mounts the script from a ConfigMap. That approach is simple for demos; for production build a small container image with the script baked in.

Next steps I can do for you
- Build and add a Kubernetes manifest that creates an `IncidentRemediation` CRD resource when an alert hits (so the real operator will pick it up).
- Create a small Dockerfile and image for the webhook receiver so it can be deployed without mounting code via ConfigMap.

Image build & deploy (recommended)

1. Build the webhook receiver image locally (replace the image name with your own registry if needed):

```powershell
cd .\webhook-receiver
docker build -t ghcr.io/aashish-26/ai-sre-alert-receiver:dev .
# push to your registry (example: GitHub Container Registry)
docker push ghcr.io/aashish-26/ai-sre-alert-receiver:dev
```

2. Apply the CRD and the image-based deployment + service and the Prometheus/Alertmanager config:

```powershell
kubectl apply -f api/v1/incidentremediation_crd.yaml
kubectl apply -f manifests/monitoring/webhook-receiver-deployment-image.yaml
kubectl apply -f manifests/monitoring/alertmanagerconfig-webhook.yaml
kubectl apply -f manifests/monitoring/prometheusrule-crashloop.yaml
```

3. Confirm the `alert-receiver` service exists and is reachable from Alertmanager (in `monitoring` namespace). AlertmanagerConfig targets `alert-receiver.monitoring.svc.cluster.local:5000` by default.

Local development notes
- You can continue to use the ConfigMap-mounted script for rapid iteration (`manifests/monitoring/webhook-receiver-deployment.yaml`). That manifest mounts the script from the repo via ConfigMap so you can change `scripts/alertmanager_webhook_receiver.py` and re-apply the ConfigMap to update the running pod.

Testing locally (no cluster)
- Run the webhook server locally and POST a sample Alertmanager payload (this will exercise the same code path but fall back to local audit files when the Kubernetes API is unavailable):

```powershell
python .\scripts\alertmanager_webhook_receiver.py

# in another shell:
$payload = @'
{
  "receiver": "ai-sre-webhook",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {"alertname": "PodCrashLooping", "namespace": "default", "pod": "demo-crashpod"},
      "annotations": {"description": "Simulated CrashLoopBackOff for demo-crashpod"}
    }
  ]
}
'@
Invoke-RestMethod -Uri http://127.0.0.1:5000/alert -Method POST -Body $payload -ContentType 'application/json'
```

You should see an audit file created under `./audit/logs/` unless the script could create a CRD in-cluster.
