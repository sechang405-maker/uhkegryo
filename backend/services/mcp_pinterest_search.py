"""Convert MCP Pinterest tool responses to the worker contract."""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging

from backend.schemas.enums import FailureCode, ReasonCode, Role
from backend.schemas.models import PinResult
from backend.services.failure_mapping import OperationalFailure
from backend.services.response_assembler import RoleSearchOutcome

logger = logging.getLogger(__name__)


def pop_search_diagnostics(payload: dict) -> object:
    """Remove observation-only diagnostics from structured and text MCP results."""
    diagnostics = payload.pop("_search_trace", None)
    for block in payload.get("content", []) if isinstance(payload.get("content"), list) else []:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            continue
        try:
            value = json.loads(block["text"])
        except ValueError:
            continue
        if isinstance(value, dict) and "_search_trace" in value:
            nested = value.pop("_search_trace")
            if diagnostics is None:
                diagnostics = nested
            block["text"] = json.dumps(value, ensure_ascii=False)
    return diagnostics

def parse_search_result(role: Role, payload: object) -> RoleSearchOutcome:
    if isinstance(payload, Mapping) and isinstance(payload.get("content"), list):
        for block in payload["content"]:
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                try:
                    payload = json.loads(block["text"])
                    break
                except ValueError:
                    continue
    if (isinstance(payload, Mapping)
            and payload.get("failure_code") == FailureCode.CONFIGURATION_ERROR.value):
        raise OperationalFailure(FailureCode.CONFIGURATION_ERROR)
    try:
        if not isinstance(payload, Mapping) or payload.get("role") != role.value:
            raise ValueError("MCP search role mismatch")
        raw_pins = payload["pins"]
        if not isinstance(raw_pins, list) or len(raw_pins) > 8:
            raise ValueError("MCP search pin count invalid")
        pins = [PinResult.model_validate(pin) for pin in raw_pins]
        code = ReasonCode(payload["code"]) if payload.get("code") else None
        if code not in (None, ReasonCode.PIN_RESULTS_EMPTY, ReasonCode.PIN_SEARCH_UNAVAILABLE):
            raise ValueError("MCP search code invalid")
        return RoleSearchOutcome(role=role, pins=pins, code=code)
    except (KeyError, TypeError, ValueError):
        logger.warning("MCP search response invalid")
        return RoleSearchOutcome(role=role, pins=[], code=ReasonCode.PIN_SEARCH_UNAVAILABLE)
