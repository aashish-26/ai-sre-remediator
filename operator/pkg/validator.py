"""Validator for MCP responses against local templates.

This module loads YAML templates from the repo `templates/` directory and
provides a `validate` function which ensures an MCP response:
 - references an existing template id
 - has an allowed/known action
 - includes required parameters (e.g. pod_name, namespace)
 - has confidence >= threshold

If validation fails, callers should log or create an IncidentRemediation CRD
for auditing; for now this module returns a (bool, reason) tuple.
"""

from pathlib import Path
import logging
import re
from typing import Any, Dict, Optional, Tuple

try:
	import yaml
except Exception:  # pragma: no cover - YAML dependency not present
	yaml = None

_PLACEHOLDER_RE = re.compile(r"{{\s*([^}\s]+)\s*}}")


def load_templates(templates_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
	"""Load all YAML templates from `templates_dir` (or repo `templates/`).

	Returns a mapping of template_id -> template dict.
	"""
	if templates_dir is None:
		templates_dir = Path(__file__).resolve().parents[2] / "templates"
	templates_dir = Path(templates_dir)

	templates: Dict[str, Dict[str, Any]] = {}
	if not templates_dir.exists():
		logging.warning("Templates directory not found: %s", templates_dir)
		return templates

	if yaml is None:
		logging.error("PyYAML is required to load templates but is not available")
		return templates

	for p in templates_dir.glob("*.yaml"):
		try:
			data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
			tid = data.get("id")
			if not tid:
				logging.warning("Template %s missing 'id'; skipping", p)
				continue
			templates[tid] = data
		except Exception:
			logging.exception("Failed to load template %s", p)

	return templates


def _extract_placeholders(s: str) -> set:
	return set(_PLACEHOLDER_RE.findall(s or ""))


def validate(
	mcp_resp: Dict[str, Any],
	context: Optional[Dict[str, Any]] = None,
	templates: Optional[Dict[str, Dict[str, Any]]] = None,
	threshold: float = 0.6,
) -> Tuple[bool, str]:
	"""Validate an MCP response against loaded templates.

	Returns (True, "ok") when valid, otherwise (False, reason).
	"""
	if templates is None:
		templates = load_templates()

	# Confidence check
	conf = mcp_resp.get("confidence")
	if conf is None:
		return False, "missing confidence"
	try:
		conf_val = float(conf)
	except Exception:
		return False, "invalid confidence value"
	if conf_val < float(threshold):
		return False, f"confidence {conf_val} below threshold {threshold}"

	# Template existence
	template_id = mcp_resp.get("template_id")
	if not template_id:
		return False, "missing template_id"
	template = templates.get(template_id)
	if not template:
		return False, f"unknown template_id: {template_id}"

	# Action known: action should either equal template_id or be a known template
	action = mcp_resp.get("action")
	if not action:
		return False, "missing action"
	if action != template_id and action not in templates:
		return False, f"unknown action: {action}"

	# Ensure the kubectl template parameters exist in either the response or the context
	kubectl_tpl = template.get("kubectl", "")
	placeholders = _extract_placeholders(kubectl_tpl)
	missing = []
	for ph in placeholders:
		if ph in mcp_resp:
			continue
		if context and ph in context:
			continue
		missing.append(ph)
	if missing:
		return False, f"missing parameters: {', '.join(missing)}"

	# Ensure MCP returned a fully-substituted `command` (no leftover placeholders)
	cmd = mcp_resp.get("command", "")
	if "{{" in cmd or "}}" in cmd:
		return False, "command contains unsubstituted placeholders"

	return True, "ok"


__all__ = ["load_templates", "validate"]
