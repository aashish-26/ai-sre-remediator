"""Test script to simulate Alertmanager webhook processing without HTTP.

This duplicates the processing logic from the webhook receiver: it builds a
payload like Alertmanager would send and invokes the operator simulation
pipeline (mcp_client -> validator -> executor) to produce an audit entry.
"""
import json
from pathlib import Path
import logging
import importlib.util

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('test_alert')

repo_root = Path(__file__).resolve().parents[1]

def load_module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    mcp_mod = load_module_from(repo_root / 'ai_operator' / 'pkg' / 'mcp_client.py', 'mcp_client')
    validator_mod = load_module_from(repo_root / 'ai_operator' / 'pkg' / 'validator.py', 'validator')
    executor_mod = load_module_from(repo_root / 'ai_operator' / 'pkg' / 'executor.py', 'executor')
except Exception:
    from ai_operator.pkg import mcp_client as mcp_mod
    from ai_operator.pkg import validator as validator_mod
    from ai_operator.pkg import executor as executor_mod


def main():
    payload = {
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

    alerts = payload.get('alerts', [])
    logger.info('Processing %d alerts', len(alerts))

    for a in alerts:
        labels = a.get('labels', {}) or {}
        annotations = a.get('annotations', {}) or {}
        ns = labels.get('namespace', 'default')
        pod = labels.get('pod') or labels.get('instance') or 'unknown-pod'

        context = {
            'namespace': ns,
            'pod_name': pod,
            'logs': annotations.get('description', '<no logs>'),
            'metrics': {},
            'event_type': 'ALERTMANAGER'
        }

        logger.info('Triggering operator flow with context: %s', json.dumps(context))

        mcp_resp = mcp_mod.query_mcp(context)
        logger.info('MCP response: %s', json.dumps(mcp_resp))
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
        logger.info('Audit file created: %s', audit_path)


if __name__ == '__main__':
    main()
