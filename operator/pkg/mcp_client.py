"""mcp_client module - provides a mocked query_mcp function.

This is a lightweight placeholder to be replaced with a real MCP HTTP
client implementation later.
"""

from typing import Any, Dict


def query_mcp(context: Dict[str, Any]) -> Dict[str, Any]:
	"""
	Mocked MCP query function.

	Replace this with an actual HTTP call to the MCP service later.

	Args:
		context: dict that may include keys like 'pod_name' and 'namespace'.

	Returns:
		A dict representing the MCP response with action, template_id,
		command, confidence, and rationale.
	"""
	pod = context.get("pod_name") or context.get("pod") or "<unknown-pod>"
	ns = context.get("namespace") or context.get("ns") or "default"

	return {
		"action": "restart-pod",
		"template_id": "restart-pod",
		"command": f"kubectl delete pod {pod} -n {ns}",
		"confidence": 0.85,
		"rationale": "CrashLoopBackOff detected",
	}


__all__ = ["query_mcp"]
