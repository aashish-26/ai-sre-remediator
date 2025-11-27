"""
Validator for MCP responses and templates.

Exposes:
- load_templates() -> dict mapping template_id -> template dict
- validate(mcp_resp, context, templates, threshold) -> (bool, reason_str)

Expect templates to be YAML files in project "templates" directory and have a top-level "id".
"""
from typing import Dict, Any, Tuple
import pathlib
import yaml
import logging

logger = logging.getLogger(__name__)

def load_templates() -> Dict[str, Dict[str, Any]]:
    proj_root = pathlib.Path(__file__).resolve().parents[2]
    templates_dir = proj_root / "templates"
    templates = {}
    if not templates_dir.exists():
        logger.warning("Templates directory not found: %s", templates_dir)
        return templates

    for p in templates_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            tid = data.get("id")
            if not tid:
                logger.warning("Template %s missing 'id'; skipping", p)
                continue
            templates[tid] = data
        except Exception:
            logger.exception("Failed to load template %s", p)
    return templates

def validate(mcp_resp: Dict[str, Any], context: Dict[str, Any], templates: Dict[str, Any], threshold: float) -> Tuple[bool, str]:
    # Basic checks:
    # 1) mcp_resp must be a dict and include 'template_id'
    # 2) template must exist in templates unless template_id == 'none'
    # 3) confidence must meet threshold
    if not isinstance(mcp_resp, dict):
        return False, "mcp_resp not a dict"

    tid = mcp_resp.get("template_id", "")
    if not tid or tid == "none":
        return True, "no-op response"

    tpl = templates.get(tid)
    if not tpl:
        return False, f"template '{tid}' not found"

    try:
        confidence = float(mcp_resp.get("confidence", mcp_resp.get("confidence", 0.0)))
    except Exception:
        confidence = 0.0

    if confidence < threshold:
        return False, f"confidence {confidence} below threshold {threshold}"

    # Basic param check: if template has variables referenced in kubectl block,
    # ensure those keys exist in the combined context/response. Simple regex to find {{ var }}.
    import re
    kubectl_tpl = tpl.get("kubectl", "") or ""
    vars_found = set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", kubectl_tpl))
    combined = {**(context or {}), **(mcp_resp or {})}
    missing = [v for v in vars_found if v not in combined or combined.get(v) in (None, "")]
    if missing:
        return False, f"missing template params: {missing}"

    return True, "ok"
