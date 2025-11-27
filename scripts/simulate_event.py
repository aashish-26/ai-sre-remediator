import logging
import json
from pathlib import Path
import importlib.util
import sys
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulator")

repo_root = Path(__file__).resolve().parents[1]

# Helper to load a module from file path without importing the package
def load_module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Load small modules directly to avoid colliding with the stdlib 'operator'
mcp_mod = load_module_from(repo_root / "ai_operator" / "pkg" / "mcp_client.py", "mcp_client")
validator_mod = load_module_from(repo_root / "ai_operator" / "pkg" / "validator.py", "validator")
executor_mod = load_module_from(repo_root / "ai_operator" / "pkg" / "executor.py", "executor")

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
container_statuses = obj.get("status", {}).get("containerStatuses", []) or []
restart_count = sum(cs.get("restartCount", 0) for cs in container_statuses)

context = {
    "namespace": ns,
    "pod_name": name,
    "logs": "<simulated logs>",
    "metrics": {"restart_count": restart_count},
    "event_type": mock_event.get("type"),
}

logger.info("Simulating MCP query with context: %s", json.dumps(context))

# Query mocked MCP
mcp_resp = mcp_mod.query_mcp(context)
logger.info("MCP response: %s", json.dumps(mcp_resp))

# Load templates then validate
templates = validator_mod.load_templates()

# Set the threshold you want the validator to use.
# Adjust this number if your validator expects a different default.
THRESHOLD = 0.75

# Call validator.validate. Some versions require a `threshold` positional arg;
# others may accept it as a kwarg. Try both patterns and provide clear error if neither works.
try:
    # Preferred: pass threshold as keyword
    valid, reason = validator_mod.validate(mcp_resp, context=context, templates=templates, threshold=THRESHOLD)
except TypeError as e_kw:
    try:
        # Fallback: pass threshold as positional (after templates)
        valid, reason = validator_mod.validate(mcp_resp, context, templates, THRESHOLD)
    except Exception as e_pos:
        logger.error("Validator.validate call failed. Traceback follows.")
        logger.error(traceback.format_exc())
        sys.exit(1)

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
