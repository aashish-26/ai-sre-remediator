"""
Simple mock MCP client used for local testing.
Function: query_mcp(context) -> dict
Returns a recommendation dict with keys:
  - template_id: string
  - confidence: float
  - action: string
  - rationale: string
  - any additional params used by templates
"""
from typing import Dict, Any
import random

def query_mcp(context: Dict[str, Any]) -> Dict[str, Any]:
    # Basic heuristic mock: if restart_count > 0 or pod phase is Failed,
    # recommend restart-pod, otherwise no-op.
    phase = context.get("metrics", {}).get("phase") or context.get("event_type") or ""
    restart_count = context.get("metrics", {}).get("restart_count", 0)
    pod_name = context.get("pod_name", "")
    namespace = context.get("namespace", "default")

    if restart_count and restart_count > 0:
        tpl = "restart-pod"
        confidence = 0.9
    elif phase and str(phase).lower() in ("failed", "unknown"):
        tpl = "restart-pod"
        confidence = 0.75
    else:
        tpl = "none"
        confidence = 0.1

    # Basic recommendation structure expected by operator_main
    return {
        "action": "execute" if tpl != "none" else "none",
        "template_id": tpl,
        "confidence": float(confidence),
        "rationale": f"Mock recommendation based on restart_count={restart_count}, phase={phase}",
        # include common params templates might reference
        "pod_name": pod_name,
        "namespace": namespace,
    }
