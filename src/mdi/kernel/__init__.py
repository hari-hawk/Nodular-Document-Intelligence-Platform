"""Kernel — industry-agnostic plumbing.

The kernel knows nothing about industries. It provides ingest, the LLM
gateway, the pack loader, the job queue, auth, and observability.
"""
from mdi.kernel import auth, ingest, llm_gateway, observability, pack_loader, settings

__all__ = ["auth", "ingest", "llm_gateway", "observability", "pack_loader", "settings"]
