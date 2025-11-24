"""Simple Kopf operator skeleton (annotated)

This module provides a minimal, local-friendly operator entrypoint using `kopf`.

Flow summary:
- Load Kubernetes config (in-cluster when running inside k8s; kubeconfig otherwise).
- Register a startup handler to perform any early initialization.
- Register an event handler for Pod events; build a tiny "recommendation" object
  and log it. This demonstrates the operator's event -> reasoning -> recommendation flow.

Next extension points:
- Replace the `rec` construction with a call to the MCP client to get a recommendation.
- Validate the MCP response using `operator/pkg/validator.py` against `templates/`.
- Use the executor (`operator/pkg/executor.py`) to perform dry-run or apply actions.
"""

import os
import json
import logging

import kopf
import kubernetes


# Load Kubernetes configuration:
# - When running inside a cluster, the environment variable
#   `KUBERNETES_SERVICE_HOST` is typically present and we load in-cluster config.
# - For local development (minikube, kind), fall back to the user's kubeconfig.
if os.getenv("KUBERNETES_SERVICE_HOST"):
	kubernetes.config.load_incluster_config()
else:
	# This will read from ~/.kube/config by default
	kubernetes.config.load_kube_config()


@kopf.on.startup()
def startup(logger, **_):
	"""Startup hook called when the operator process starts.

	Use this to initialize clients, caches, metrics, or to validate that
	required resources (templates, schema files) are present.
	"""
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

	# Build a minimal recommendation structure. In a full implementation this
	# would be created by calling the MCP client with a constrained prompt,
	# then running the response through the validator.
	rec = {
		"action": "none",
		"template_id": "",
		"command": "",
		"confidence": 0.0,
		"rationale": f"Observed pod event: {phase}"
	}

	# For now, simply emit the recommendation to logs (dry-run). Downstream
	# components would persist this to an audit store or GitOps commit.
	logger.info("Recommendation: %s", json.dumps(rec))

	# Example extension (pseudo-code):
	# mcp_resp = mcp_client.suggest_action(context)
	# valid = validator.validate(mcp_resp)
	# if valid and mcp_resp['confidence'] > CONF_THRESHOLD:
	#     executor.apply(mcp_resp)

