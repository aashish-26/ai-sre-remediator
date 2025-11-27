"""
Executor helper for rendering kubectl templates and performing a dry-run.

Exposes:
- render_template(tpl_str, params) -> str
- execute_dry_run(cmd_str) -> dict (trace)
- record_audit(trace, context, mcp_resp, tpl, command=cmd) -> str (path to JSON file)
"""
from typing import Dict, Any
import pathlib
import json
import time
import logging
import uuid
import datetime
import traceback

logger = logging.getLogger(__name__)

try:
    from jinja2 import Template
except Exception:
    Template = None


def render_template(tpl_str: str, params: Dict[str, Any]) -> str:
    if not tpl_str:
        return ""
    if Template is None:
        # fallback: simple python-format style replacement for {{ var }}
        s = tpl_str
        for k, v in (params or {}).items():
            s = s.replace("{{ " + k + " }}", str(v))
            s = s.replace("{{" + k + "}}", str(v))
        return s
    template = Template(tpl_str)
    return template.render(**(params or {}))


def execute_dry_run(cmd_str: str) -> Dict[str, Any]:
    # Simulate running the command in dry-run: return a trace dict.
    logger.info("DRY-RUN: %s", cmd_str)
    trace_id = uuid.uuid4().hex
    ts = time.time()
    trace = {
        "id": trace_id,
        "timestamp": ts,
        "iso_timestamp": datetime.datetime.utcfromtimestamp(ts).isoformat() + "Z",
        "cmd": cmd_str,
        "stdout": "simulated dry-run output",
        "success": True,
    }
    # Log a short audit pointer so operators can find the audit quickly
    logger.info("DRY-RUN trace id=%s", trace_id)
    return trace


def record_audit(trace: Dict[str, Any], context: Dict[str, Any], mcp_resp: Dict[str, Any], tpl: Dict[str, Any], command: str = "") -> str:
    """
    Record the audit for a dry-run.

    Writes JSON to the project `audit/logs/<trace_id>.json` and also creates
    a small markdown summary next to it. Returns the path to the JSON file as string.
    """
    # Loud entry so callers can verify invocation
    try:
        pod_name = (context or {}).get("pod_name", "unknown")
    except Exception:
        pod_name = "unknown"
    logger.info("record_audit invoked for pod=%s", pod_name)

    # Resolve audits_dir robustly. Primary: repo root relative to package (ai_operator/pkg/executor.py -> parents[2]).
    # Fallback: current working directory.
    try:
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        audits_dir = repo_root / "audit" / "logs"
    except Exception:
        audits_dir = pathlib.Path.cwd() / "audit" / "logs"

    # Ensure directory exists
    try:
        audits_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.exception("Failed to create audit directory %s: %s", audits_dir, e)
        # Attempt fallback to cwd
        try:
            audits_dir = pathlib.Path.cwd() / "audit" / "logs"
            audits_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Fallback audits_dir resolved to %s", audits_dir)
        except Exception:
            logger.exception("Fallback creation of audit directory failed: %s", traceback.format_exc())
            raise

    logger.info("audits_dir resolved to %s", audits_dir)

    try:
        trace_id = (trace or {}).get("id") or uuid.uuid4().hex
        ts = int(time.time())
        rec = {
            "trace": trace,
            "context": context,
            "mcp_resp": mcp_resp,
            "template": tpl,
            "command": command,
            "recorded": ts,
        }

        json_path = audits_dir / f"{trace_id}.json"
        # Write JSON audit
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(rec, jf, indent=2, ensure_ascii=False)

        logger.info("Audit written: %s", json_path)

        # Create a simple markdown summary for human inspection and potential git commits
        md_path = audits_dir / f"{trace_id}.md"
        md_lines = []
        md_lines.append(f"# Audit {trace_id}")
        md_lines.append("")
        md_lines.append(f"- recorded: {datetime.datetime.utcfromtimestamp(ts).isoformat()}Z")
        md_lines.append(f"- pod: `{pod_name}`")
        md_lines.append(f"- namespace: `{(context or {}).get('namespace', '')}`")
        md_lines.append(f"- template_id: `{(mcp_resp or {}).get('template_id', '')}`")
        md_lines.append(f"- action: `{(mcp_resp or {}).get('action', '')}`")
        md_lines.append(f"- confidence: `{(mcp_resp or {}).get('confidence', 0.0)}`")
        md_lines.append("")
        if command:
            md_lines.append("## Command\n")
            md_lines.append("```")
            md_lines.append(command)
            md_lines.append("```")
            md_lines.append("")
        md_lines.append("## Payload\n")
        md_lines.append("```json")
        md_lines.append(json.dumps(rec, indent=2, ensure_ascii=False))
        md_lines.append("```")

        with open(md_path, "w", encoding="utf-8") as mf:
            mf.write("\n".join(md_lines))

        logger.info("Audit summary written: %s", md_path)

        # Return JSON path as string for callers that log it
        return str(json_path)

    except Exception:
        logger.exception("Failed to write audit files: %s", traceback.format_exc())
        raise
