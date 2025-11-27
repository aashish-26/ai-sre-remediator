import logging
import json
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulator_ai")

repo_root = Path(__file__).resolve().parents[1]

# Import modules from ai_operator package
from ai_operator.pkg import mcp_client as mcp_mod
from ai_operator.pkg import validator as validator_mod
from ai_operator.pkg import executor as executor_mod

# Minimal mock event -> build context similar to operator_main
mock_event = {
    "type": "ADDED",
    "object": {
        "metadata": {"name": "demo-crashpod", "namespace": "default"},
        "status": {"phase": "Failed", "containerStatuses": [{"restartCount": 3}]},
    },
}

obj = mock_event["object"]
name = obj.get("metadata", {}).get("name", "<noname>")
ns = obj.get("metadata", {}).get("namespace", "default")
container_statuses = obj.get('status', {}).get('containerStatuses', []) or []
restart_count = sum(cs.get('restartCount', 0) for cs in container_statuses)

context = {
    "namespace": ns,
    "pod_name": name,
    "logs": "<simulated logs>",
    "metrics": {"restart_count": restart_count},
    "event_type": mock_event.get('type')
}

logger.info("Simulating MCP query with context: %s", json.dumps(context))

# Query mocked MCP
mcp_resp = mcp_mod.query_mcp(context)
logger.info("MCP response: %s", json.dumps(mcp_resp))

# Load templates then validate
templates = validator_mod.load_templates()
valid, reason = validator_mod.validate(mcp_resp, context=context, templates=templates, threshold=0.6)
if not valid:
    logger.warning("Validator rejected: %s", reason)
else:
    logger.info("Validator accepted response; rendering and dry-run")
    tpl = templates.get(mcp_resp.get("template_id", ""), {})
    kubectl_tpl = tpl.get("kubectl", "")
    params = {**context, **mcp_resp}
    cmd = executor_mod.render_template(kubectl_tpl, params)
    mcp_resp["command"] = cmd
    trace = executor_mod.execute_dry_run(cmd)
    audit_path = executor_mod.record_audit(trace, context, mcp_resp, tpl, command=cmd)
    logger.info("Audit file created: %s", audit_path)

print("Simulation complete.")
