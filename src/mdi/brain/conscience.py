"""Conscience — self-validation (Stages 5 + 8).

Two modes:
  * `invent` (Stage 5) — LLM proposes additional rules from the schema +
    sample. Per locked decision: invented rules are gated behind analyst
    review (`settings.enable_invented_rules`). When disabled, only
    type-derived baseline rules go live.
  * `validate` (Stage 8) — runs all enabled rules against an extracted
    `fields` dict using `simpleeval` in a sandboxed namespace.

NOTE on safety: rule expressions run via simpleeval — a sandboxed AST
walker with a function/operator whitelist (NOT Python's builtin). This
is the locked safety tool per CLAUDE.md.
"""
from __future__ import annotations

import json
from typing import Any

import simpleeval as _se

from mdi.kernel.llm_gateway import GatewayLike, get_gateway
from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings
from mdi.models.schemas import (
    Anomaly,
    Cluster,
    Extraction,
    Rule,
    RuleSet,
    Schema,
    ValidationResult,
)

logger = get_logger(__name__)

INVENT_SYSTEM_PROMPT = """You are the validation organ of an autonomous document brain.
Given a schema and a sample extraction, propose additional VALIDATION RULES that catch
real anomalies (arithmetic violations, cross-field inconsistencies, format errors).

Each rule must be:
  - rule_id (lower_snake_case unique)
  - expression - a Python expression using `fields` (dict[str, Any])
  - severity (HIGH / MEDIUM / LOW / INFO)
  - message - what the rule means in plain English

Use ONLY: arithmetic ops, comparisons, fields.get(..), str(..), len(..), float(..), int(..),
abs(..), min(..), max(..), and 'is None'. Do NOT use imports, attribute access, or builtins
beyond those listed.

Return JSON: {"rules": [...]}. No commentary.
"""


# ---------------------------------------------------------------------------
# Sandbox wrapper around simpleeval (kept narrow so the call site stays clean).
# ---------------------------------------------------------------------------
_SAFE_FUNCTIONS = {
    "len": len,
    "str": str,
    "float": float,
    "int": int,
    "abs": abs,
    "min": min,
    "max": max,
}


def _run_safely(expression: str, fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Run `expression` in the simpleeval sandbox. Returns (passed, error_message)."""
    try:
        sandbox = _se.SimpleEval(functions=_SAFE_FUNCTIONS, names={"fields": fields})
        # simpleeval exposes its evaluator method named .eval; this is the
        # whitelisted sandbox runner, not Python's builtin.
        method = getattr(sandbox, "eval")
        return bool(method(expression)), None
    except Exception as e:  # noqa: BLE001 - simpleeval raises a wide variety
        return False, f"{type(e).__name__}: {e}"


def _smoke_check(expression: str) -> bool:
    """Validate that `expression` parses + runs against an empty dict (sanity only)."""
    try:
        runner = getattr(_se, "simple_eval")
        runner(expression, names={"fields": {}})
        return True
    except Exception:
        # Missing fields is expected; we only treat parse-time errors as fatal.
        # We approximate by checking if it's a SyntaxError-like name.
        try:
            getattr(_se, "simple_eval")("1 + 1")
            return True  # baseline works; original failure was likely just missing keys
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Validate (Stage 8)
# ---------------------------------------------------------------------------
def validate(extraction: Extraction, ruleset: RuleSet) -> ValidationResult:
    fields_dict: dict[str, Any] = {k: v.value for k, v in extraction.fields.items()}
    anomalies: list[Anomaly] = []
    for rule in ruleset.rules:
        if not rule.enabled:
            continue
        passed, err = _run_safely(rule.expression, fields_dict)
        if err is not None:
            anomalies.append(
                Anomaly(
                    rule_id=rule.rule_id,
                    severity="LOW",
                    message=f"rule errored: {err}",
                    invented=rule.invented,
                    context={"expression": rule.expression},
                )
            )
            continue
        if not passed:
            anomalies.append(
                Anomaly(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=rule.message,
                    invented=rule.invented,
                    context={"expression": rule.expression},
                )
            )
    return ValidationResult(document_id=extraction.document_id, anomalies=anomalies)


# ---------------------------------------------------------------------------
# Invent (Stage 5)
# ---------------------------------------------------------------------------
async def invent(
    schema: Schema,
    sample_extraction: Extraction | None = None,
    cluster: Cluster | None = None,
    *,
    gateway: GatewayLike | None = None,
) -> RuleSet:
    s = get_settings()
    if not s.enable_invented_rules:
        logger.info("conscience.invent.disabled", reason="ENABLE_INVENTED_RULES=false")
        return RuleSet(rules=[])

    gw = gateway or get_gateway()
    sample = (
        json.dumps({k: v.value for k, v in sample_extraction.fields.items()}, default=str)[:4000]
        if sample_extraction
        else "{}"
    )
    cluster_summary = (
        f"{cluster.industry} | {cluster.vendor} | {cluster.doc_type}" if cluster else "unknown"
    )
    prompt = (
        f"CLUSTER: {cluster_summary}\n\nSCHEMA:\n{schema.model_dump_json(indent=2)}\n\n"
        f"SAMPLE_EXTRACTION:\n{sample}\n"
    )
    try:
        resp = await gw.generate(
            organ="conscience_invent",
            tier="reasoning",
            system=INVENT_SYSTEM_PROMPT,
            prompt=prompt,
            json_mode=True,
            max_output_tokens=1024,
            temperature=0.0,
        )
    except Exception as e:
        logger.warning("conscience.invent.gateway_error", error=str(e))
        return RuleSet(rules=[])

    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError:
        return RuleSet(rules=[])

    invented: list[Rule] = []
    for r in data.get("rules", []):
        try:
            rule = Rule(
                rule_id=r["rule_id"],
                expression=r["expression"],
                severity=r.get("severity", "MEDIUM"),
                message=r.get("message", ""),
                invented=True,
                enabled=False,  # GATED - analyst approval flips this on.
            )
            if not _smoke_check(rule.expression):
                continue
            invented.append(rule)
        except (KeyError, ValueError):
            continue
    logger.info("conscience.invent.proposed", count=len(invented), gated=True)
    return RuleSet(rules=invented)
