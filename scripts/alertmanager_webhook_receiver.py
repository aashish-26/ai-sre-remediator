#!/usr/bin/env python3
"""
Alertmanager webhook receiver (HTTP) that triggers the operator flow.

Behavior summary:
- If a reachable Kubernetes API is available, the receiver will create an
  `IncidentRemediation` CR in the alert's namespace so the operator can
  reconcile it.
- If no Kubernetes API is reachable, or if you set `DISABLE_CR_CREATION=true`,
  the receiver falls back to running the operator pipeline locally and writing
  audit files under `./audit/logs/`.

Usage (local dev):
  DISABLE_CR_CREATION=true python scripts/alertmanager_webhook_receiver.py

Comments are added inline for learning.
"""

import logging
import json
import os
import time
from flask import Flask, request, jsonify
from pathlib import Path
import importlib.util

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('alert_receiver')

app = Flask(__name__)

repo_root = Path(__file__).resolve().parents[1]


def load_module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load operator helpers (mcp client, validator, executor). We try to load
# directly from the repo so you can iterate without installing the package.
try:
    mcp_mod = load_module_from(repo_root / 'ai_operator' / 'pkg' / 'mcp_client.py', 'mcp_client')
    validator_mod = load_module_from(repo_root / 'ai_operator' / 'pkg' / 'validator.py', 'validator')
    executor_mod = load_module_from(repo_root / 'ai_operator' / 'pkg' / 'executor.py', 'executor')
except Exception:
    # Fallback to package import when installed or in packaged image
    from ai_operator.pkg import mcp_client as mcp_mod
    from ai_operator.pkg import validator as validator_mod
    from ai_operator.pkg import executor as executor_mod


def try_setup_k8s_client():
    """Attempt to configure a Kubernetes client and return (co_api, k8s_client).

    Returns (None, None) when no working client is available. Honor the
    `DISABLE_CR_CREATION` env var so local dev doesn't spam kube attempts.
    """
    if os.getenv('DISABLE_CR_CREATION', 'false').lower() in ('1', 'true', 'yes'):
        logger.info('DISABLE_CR_CREATION set; skipping Kubernetes client setup')
        return None, None

    try:
        import kubernetes
        # Prefer in-cluster when running in k8s; otherwise use kubeconfig
        if os.getenv('KUBERNETES_SERVICE_HOST'):
            kubernetes.config.load_incluster_config()
        else:
            kubernetes.config.load_kube_config()

        api = kubernetes.client.CustomObjectsApi()

        # Quick reachability check: try a simple call to the API server version
        try:
            kubernetes.client.VersionApi().get_code()
        except Exception:
            # If the API server is unreachable, treat as not available
            logger.info('Kubernetes API not reachable from this process; will use local audit fallback')
            return None, None

        return api, kubernetes.client
    except Exception:
        logger.info('Kubernetes client unavailable; will use local audit fallback')
        return None, None


@app.route('/healthz')
def healthz():
    return 'ok'


@app.route('/alert', methods=['POST'])
def alert():
    """Handle Alertmanager webhook POSTs.

    For each alert in the payload we either create an IncidentRemediation CR
    or run the operator pipeline locally (and write an audit file).
    """
    payload = request.get_json(force=True)
    logger.info('Received alert payload: %s', json.dumps(payload))

    alerts = payload.get('alerts', []) if isinstance(payload, dict) else []
    if not alerts:
        return jsonify({'status': 'no alerts'}), 400

    co_api, k8s_client = try_setup_k8s_client()
    created = 0

    for a in alerts:
        labels = a.get('labels', {}) or {}
        annotations = a.get('annotations', {}) or {}
        ns = labels.get('namespace', 'default')
        pod = labels.get('pod') or labels.get('instance') or 'unknown-pod'

        # Build context the operator expects
        context = {
            'namespace': ns,
            'pod_name': pod,
            'logs': annotations.get('description', '<no logs>'),
            'metrics': {},
            'event_type': 'ALERTMANAGER'
        }

        logger.info('Processing alert into operator flow with context: %s', json.dumps(context))

        # Query MCP (may be mocked) and prepare response
        try:
            mcp_resp = mcp_mod.query_mcp(context)
        except Exception:
            logger.exception('MCP query failed; building fallback response')
            mcp_resp = {
                'action': 'none',
                'template_id': '',
                'confidence': 0.0,
                'rationale': 'MCP query failed',
            }

        # If we can talk to k8s, create a CR; otherwise run local audit flow
        if co_api is not None:
            group = 'ai-sre.example.com'
            version = 'v1'
            plural = 'incidentremediations'

            timestamp = int(time.time())
            safe_pod = pod.replace('.', '-').replace('_', '-')
            cr_name = f"ir-{safe_pod}-{timestamp}"

            body = {
                'apiVersion': f'{group}/{version}',
                'kind': 'IncidentRemediation',
                'metadata': {'name': cr_name, 'namespace': ns},
                'spec': {
                    'source': 'alertmanager',
                    'context': context,
                    'alerts': {'labels': labels, 'annotations': annotations},
                    'mcp_response': mcp_resp,
                },
            }

            try:
                co_api.create_namespaced_custom_object(group, version, ns, plural, body)
                logger.info('Created IncidentRemediation CR %s/%s', ns, cr_name)
                created += 1
            except Exception:
                logger.exception('Failed to create CR; falling back to local audit')
                # local audit fallback: validate & write audit
                try:
                    templates = validator_mod.load_templates()
                    valid, reason = validator_mod.validate(mcp_resp, context=context, templates=templates, threshold=0.6)
                    if valid:
                        tpl = templates.get(mcp_resp.get('template_id', ''), {})
                        kubectl_tpl = tpl.get('kubectl', '')
                        params = {**context, **mcp_resp}
                        cmd = executor_mod.render_template(kubectl_tpl, params)
                        mcp_resp['command'] = cmd
                        trace = executor_mod.execute_dry_run(cmd)
                        audit_path = executor_mod.record_audit(trace, context, mcp_resp, tpl, command=cmd)
                        logger.info('Local audit written: %s', audit_path)
                except Exception:
                    logger.exception('Local audit fallback failed')

        else:
            # No kube client available — run the pipeline locally and write audit
            try:
                templates = validator_mod.load_templates()
                valid, reason = validator_mod.validate(mcp_resp, context=context, templates=templates, threshold=0.6)
                if not valid:
                    logger.warning('Validator rejected: %s', reason)
                    continue
                tpl = templates.get(mcp_resp.get('template_id', ''), {})
                kubectl_tpl = tpl.get('kubectl', '')
                params = {**context, **mcp_resp}
                cmd = executor_mod.render_template(kubectl_tpl, params)
                mcp_resp['command'] = cmd
                trace = executor_mod.execute_dry_run(cmd)
                audit_path = executor_mod.record_audit(trace, context, mcp_resp, tpl, command=cmd)
                logger.info('Local audit written: %s', audit_path)
            except Exception:
                logger.exception('Local processing failed')

    return jsonify({'status': 'processed', 'count': len(alerts), 'created_crs': created})


if __name__ == '__main__':
    # Local development: set DISABLE_CR_CREATION=true to always use local audit
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')))
