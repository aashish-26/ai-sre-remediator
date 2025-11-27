"""Simple Kopf operator skeleton (annotated)

This module provides a minimal, local-friendly operator entrypoint using `kopf`.

Flow summary:
- Load Kubernetes config (in-cluster when running inside k8s; kubeconfig otherwise).
- Register a startup handler to perform any early initialization.
- Register an event handler for Pod events; build a tiny "recommendation" object
  and log it. This demonstrates the operator's event -> reasoning -> recommendation flow.

Next extension points:
    - Replace the `rec` construction with a call to the MCP client to get a recommendation.
    - Validate the MCP response using `ai_operator/pkg/validator.py` against `templates/`.
    - Use the executor (`ai_operator/pkg/executor.py`) to perform dry-run or apply actions.
"""

import os
import json
import logging
import time

import kopf
from kubernetes.config.config_exception import ConfigException
import kubernetes
import hashlib

from prometheus_client import Counter, Histogram, start_http_server

from ai_operator.pkg.mcp_client import query_mcp
from ai_operator.pkg import validator
from ai_operator.pkg import executor
from ai_operator.pkg import webhook

import sys
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-operator")
logger.info("Starting ai-operator module; WEBHOOK_PORT=%s METRICS_PORT=%s",
            os.getenv("WEBHOOK_PORT"), os.getenv("METRICS_PORT"))

# Load templates once at module import for performance; can be reloaded if needed
try:
    TEMPLATES = validator.load_templates()
    logger.info("Loaded %d templates", len(TEMPLATES))
except Exception:
    logger.exception("Failed to load templates; continuing with empty registry")
    TEMPLATES = {}
# Configurable confidence threshold (env var overrides default)
CONF_THRESHOLD = float(os.getenv("MCP_CONF_THRESHOLD", "0.6"))


# Prometheus metrics (exported on startup)
DECISIONS = Counter("ai_operator_decisions_total", "Total decisions made", ["outcome"])
MCP_LATENCY = Histogram("ai_operator_mcp_latency_seconds", "Latency for MCP calls (s)")
EXECUTOR_ACTIONS = Counter("ai_operator_actions_total", "Executor actions executed", ["mode", "result"])
VALIDATION_REJECTIONS = Counter("ai_operator_validation_rejections_total", "Validation rejections")


# Load Kubernetes configuration:
# - When running inside a cluster, the environment variable
#   `KUBERNETES_SERVICE_HOST` is typically present and we load in-cluster config.
# - For local development (minikube, kind), fall back to the user's kubeconfig.

logger = logging.getLogger(__name__)

KUBE_AVAILABLE = False

def load_kube_config_safe():
    global KUBE_AVAILABLE
    # Prefer in-cluster (when running inside k8s)
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
        KUBE_AVAILABLE = True
        return
    except ConfigException:
        logger.debug("No in-cluster kube config found, trying kubeconfig file")

    # Fallback to kubeconfig on disk (for local dev). Respect KUBECONFIG env var.
    try:
        kubernetes.config.load_kube_config()
        logger.info("Loaded kubeconfig from filesystem")
        KUBE_AVAILABLE = True
        return
    except ConfigException:
        logger.warning("No kube config available inside container; continuing in degraded mode. "
                       "Kubernetes API calls will be disabled until a valid config is provided.")
        KUBE_AVAILABLE = False

# call it during startup (before any Kubernetes API objects are created)
load_kube_config_safe()

@kopf.on.startup()
def startup(logger, **_):
    """Startup hook called when the operator process starts.

    Use this to initialize clients, caches, metrics, or to validate that
    required resources (templates, schema files) are present.
    """
    metrics_port = int(os.getenv("METRICS_PORT", "9100"))
    logger.info("Starting metrics server on :%d", metrics_port)
    try:
        start_http_server(metrics_port)
    except Exception:
        logger.exception("Failed to start metrics HTTP server")
    # Start the operator webhook receiver (for Alertmanager webhook delivery).
    # Use `WEBHOOK_PORT` env var (default 5001) to avoid conflicts (e.g. Jenkins on 8080).
    try:
        webhook_port = int(os.getenv("WEBHOOK_PORT", "5001"))
        webhook.run_webhook_server(port=webhook_port)
        logger.info("Webhook receiver started on :%d", webhook_port)
    except Exception:
        logger.exception("Failed to start webhook receiver")
    logger.info("ai-operator (dry-run) starting")


@kopf.on.event('', 'v1', 'pods')
def pod_event(event, logger, **_):
    """Handle Pod events.

    `event` is the raw dict provided by kopf/kubernetes. Key information lives in
    `event['object']` which is the current Pod object. `event['type']` is the
    event type (ADDED/DELETED/MODIFIED).

    This handler demonstrates a few things:
    - How to extract relevant metadata from the event object (namespace/name/status).
    - How to synthesize a lightweight "recommendation" that would normally be
      produced by a reasoning component (MCP client).
    - Where you'd plug in validator/executor calls.
    """

    # The object field contains the Kubernetes Pod manifest (as a dict)
    obj = event.get('object', {})

    # Extract common metadata safely (guarding against missing keys)
    name = obj.get('metadata', {}).get('name', '<noname>')
    ns = obj.get('metadata', {}).get('namespace', 'default')

    # Pod phase is in status.phase (Pending/Running/Succeeded/Failed/Unknown)
    phase = obj.get('status', {}).get('phase', 'Unknown')

    # Log a concise event line so devs can quickly see operator activity
    logger.info("EVENT: %s/%s phase=%s type=%s", ns, name, phase, event.get('type'))

    # Build a context for MCP: namespace, pod_name, last 10 logs, and a
    # short (mock) metrics summary. Attempt to fetch real logs; fall back
    # to a placeholder when unavailable.
    pod_logs = "<logs unavailable: kube api disabled>"
if KUBE_AVAILABLE:
    try:
        v1 = kubernetes.client.CoreV1Api()
        pod_logs = v1.read_namespaced_pod_log(name=name, namespace=ns, tail_lines=10)
    except Exception as e:
        pod_logs = f"<logs unavailable: {e}>"
else:
    logger.debug("Kubernetes API disabled; skipping pod log fetch for %s/%s", ns, name)


    # Mock metrics summary for now (replace with real metrics later).
    container_statuses = obj.get('status', {}).get('containerStatuses', []) or []
    restart_count = sum(cs.get('restartCount', 0) for cs in container_statuses)
    metrics_summary = {
        "mock_cpu_usage": "50m",
        "mock_memory_usage": "128Mi",
        "restart_count": restart_count,
    }

    context = {
        "namespace": ns,
        "pod_name": name,
        "logs": pod_logs,
        "metrics": metrics_summary,
        "event_type": event.get('type')
    }

    # Audit: log the full prompt/context we send to the MCP
    logger.info("MCP prompt: %s", json.dumps(context))

    # Query the MCP (mocked) and compute a response id (hash) for audit.
    try:
        start_ts = time.time()
        mcp_resp = query_mcp(context)
        MCP_LATENCY.observe(time.time() - start_ts)
        resp_json = json.dumps(mcp_resp)
        resp_id = hashlib.sha256(resp_json.encode()).hexdigest()
        logger.info("MCP response id=%s", resp_id)
        logger.info("MCP response: %s", resp_json)

        # Validate MCP response against templates and parameter requirements.
        valid, reason = validator.validate(
            mcp_resp,
            context=context,
            templates=TEMPLATES,
            threshold=CONF_THRESHOLD,
        )

        if not valid:
            # Log rejection and create an incident placeholder for now
            VALIDATION_REJECTIONS.inc()
            DECISIONS.labels(outcome="rejected").inc()
            logger.warning("MCP response rejected by validator: %s", reason)
            logger.info("Would create IncidentRemediation CRD for audit (placeholder)")
            rec = {
                "action": "none",
                "template_id": mcp_resp.get("template_id", ""),
                "command": "",
                "confidence": mcp_resp.get("confidence", 0.0),
                "rationale": f"Rejected by validator: {reason}",
            }
        else:
            # validator accepted the MCP response; wire up dry-run + audit
            DECISIONS.labels(outcome="accepted").inc()
            rec = mcp_resp
            try:
                tpl = TEMPLATES.get(rec.get("template_id", ""), {})
                kubectl_tpl = tpl.get("kubectl", "")
                # Merge context and response so response values override
                params = {**(context or {}), **(rec or {})}
                cmd = executor.render_template(kubectl_tpl, params)
                # attach the rendered command to the recommendation for logging/audit
                rec["command"] = cmd
                trace = executor.execute_dry_run(cmd)
                executor.record_audit(trace, context, mcp_resp, tpl, command=cmd)
                EXECUTOR_ACTIONS.labels(mode="dry-run", result="ok").inc()
            except Exception:
                EXECUTOR_ACTIONS.labels(mode="dry-run", result="error").inc()
                logger.exception("Executor dry-run/audit failed")
    except Exception:
        logger.exception("MCP query failed; falling back to local recommendation")
        rec = {
            "action": "none",
            "template_id": "",
            "command": "",
            "confidence": 0.0,
            "rationale": f"Observed pod event: {phase}"
        }

    # Emit the final recommendation to logs (dry-run). Downstream components
    # would persist this to an audit store or GitOps commit.
    logger.info("Recommendation: %s", json.dumps(rec))

    # Example extension (pseudo-code):
    # mcp_resp = mcp_client.suggest_action(context)
    # valid = validator.validate(mcp_resp)
    # if valid and mcp_resp['confidence'] > CONF_THRESHOLD:
    #     executor.apply(mcp_resp)
