"""Executor helpers for dry-run and audit.

This module provides lightweight helpers used by the operator during the
dry-run phase:
- `render_template(template, params)` - render a kubectl template into a
  concrete command string (supports Jinja-like `{{var}}` placeholders or
  falls back to Python `str.format`-style substitution).
- `execute_dry_run(cmd)` - log the command and return a trace id.
- `record_audit(trace, context, mcp_response, template)` - persist an
  audit JSON file under `./audit/logs/<trace>.json`.

The implementation purposely keeps external dependencies optional so the
repository can be run in lightweight environments.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

try:
	from jinja2 import Template as JinjaTemplate
except Exception:  # pragma: no cover - jinja2 optional
	JinjaTemplate = None

# Match simple jinja-style placeholders like {{ var }} or {{ pod.name }}
_PLACEHOLDER_RE = re.compile(r"{{\s*([^}\s]+)\s*}}")


def render_template(template: str, params: Dict[str, Any]) -> str:
	"""Render a template string using `params`.

	- If `jinja2` is available, use it for rendering.
	- Otherwise, translate `{{var}}` -> `{var}` and use `str.format_map`.

	Returns the rendered command string.
	"""
	if not template:
		return ""

	# Prefer Jinja2 when available (templates are written in that style).
	if JinjaTemplate is not None:
		try:
			return JinjaTemplate(template).render(**(params or {}))
		except Exception:
			logging.exception("jinja2 template render failed; falling back")

	# Fallback: convert Jinja-style {{var}} into Python format {var}
	def _to_pyformat(m: re.Match) -> str:
		return "{" + m.group(1) + "}"

	pyfmt = _PLACEHOLDER_RE.sub(_to_pyformat, template)

	class _DotLookup(dict):
		"""Mapping wrapper to support dotted lookups in format_map.

		Example: template contains `{pod.name}` and params is {"pod": {"name": "x"}}
		then `_DotLookup(params)["pod.name"]` will return `"x"`.
		"""

		def __init__(self, source: Optional[Dict[str, Any]] = None):
			super().__init__()
			self._src = source or {}

		def __getitem__(self, key: str) -> Any:
			# If the key exists literally in source, return it.
			if key in self._src:
				return self._src[key]

			# Support dotted lookups: pod.name -> _src['pod']['name']
			if "." in key:
				parts = key.split(".")
				cur: Any = self._src
				for p in parts:
					if isinstance(cur, dict) and p in cur:
						cur = cur[p]
					else:
						raise KeyError(key)
				return cur

			# Missing key
			raise KeyError(key)

	try:
		return pyfmt.format_map(_DotLookup(params or {}))
	except Exception:
		logging.exception("Fallback template render failed")
		# Last resort: return the original template so caller can audit
		return template


def execute_dry_run(cmd: str) -> str:
	"""Perform a dry-run execution (no real kubectl calls).

	Logs the command and returns a generated `trace` id (uuid4 hex).
	"""
	trace = uuid.uuid4().hex
	logging.info("[dry-run] trace=%s cmd=%s", trace, cmd)
	# Also echo to stdout for local debugging (some runtimes capture logs)
	print(f"DRY-RUN [{trace}]: {cmd}")
	return trace


def record_audit(
	trace: str,
	context: Optional[Dict[str, Any]],
	mcp_response: Optional[Dict[str, Any]],
	template: Optional[Dict[str, Any]],
	command: Optional[str] = None,
) -> Optional[Path]:
	"""Write an audit entry JSON to `<audit_dir>/<trace>.json`.

	The audit directory defaults to `$AUDIT_DIR` if set, otherwise to
	`<repo-root>/audit/logs`.

	If the environment variable `AUDIT_COMMIT` is set to a truthy value,
	a markdown file will be created and committed to git in the repo root
	(best-effort; failures are logged).

	Returns the `Path` to the written JSON file on success, or `None` on
	failure.
	"""
	# Determine audit directory: env override -> repo-root/audit/logs
	env_dir = os.getenv("AUDIT_DIR")
	if env_dir:
		audit_dir = Path(env_dir)
	else:
		# repo root is three parents up from this file: pkg -> operator -> repo
		repo_root = Path(__file__).resolve().parents[2]
		audit_dir = repo_root / "audit" / "logs"

	try:
		audit_dir.mkdir(parents=True, exist_ok=True)
	except Exception:
		logging.exception("Failed to create audit directory %s", audit_dir)
		return None

	entry = {
		"trace": trace,
		"timestamp": datetime.utcnow().isoformat() + "Z",
		"context": context or {},
		"mcp_response": mcp_response or {},
		"template": template or {},
		"command": command or (mcp_response or {}).get("command"),
	}

	target = audit_dir / f"{trace}.json"
	try:
		with target.open("w", encoding="utf-8") as fh:
			json.dump(entry, fh, indent=2, ensure_ascii=False)
		logging.info("Audit written: %s", target)
	except Exception:
		logging.exception("Failed to write audit file %s", target)
		return None

	# Optional: create a git commit with a markdown summary if requested
	if os.getenv("AUDIT_COMMIT", "").lower() in ("1", "true", "yes"):
		try:
			md = f"# Audit {trace}\n\n- timestamp: {entry['timestamp']}\n- command: {entry['command']}\n- template: {entry['template'].get('id', '')}\n\n```\n{entry}\n```\n"
			repo_root = Path(__file__).resolve().parents[2]
			md_path = repo_root / "audit" / f"{trace}.md"
			md_path.parent.mkdir(parents=True, exist_ok=True)
			md_path.write_text(md, encoding="utf-8")
			# Run git add/commit (best-effort)
			subprocess.run(["git", "add", str(md_path)], cwd=str(repo_root))
			subprocess.run(
				["git", "commit", "-m", f"Add audit {trace}", "--", str(md_path)],
				cwd=str(repo_root),
			)
			logging.info("Audit committed to git: %s", md_path)
		except Exception:
			logging.exception("Failed to commit audit to git")

	return target


__all__ = ["render_template", "execute_dry_run", "record_audit"]
