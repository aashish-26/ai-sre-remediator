from operator.pkg.mcp_client import query_mcp
from operator.pkg import validator
from operator.pkg import executor

# operator/pkg/__init__.py
# Expose only lightweight names. Import heavy submodules lazily in their callers.
__all__ = ["mcp_client", "validator", "executor"]

