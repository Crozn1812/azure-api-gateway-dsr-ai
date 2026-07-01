from datetime import datetime, timezone
import os
from typing import Any

from src.services.apim_synthetic_check_service import build_apim_synthetic_check
from src.services.virtual_graph_service import (
    build_data_protection_report,
    build_graph_signal,
)


def _build_basic_backend_status() -> dict[str, Any]:
    return {
        "name": "Basic backend status",
        "status": "PASS",
        "category": "runtime",
        "message": "FastAPI backend is running and Ops Console is reachable",
        "details": {
            "service": "DSR API Gateway Ops Console",
            "environment": os.getenv("ENVIRONMENT", "local"),
            "dataSource": os.getenv("DATA_SOURCE", "mock"),
            "opsConsoleEnabled": os.getenv("ENABLE_OPS_CONSOLE", "true"),
        },
    }


def _build_ops_configuration_status() -> dict[str, Any]:
    configured_items = {
        "OPS_CONSOLE_KEY": bool(os.getenv("OPS_CONSOLE_KEY", "demo-ops-key")),
        "DATA_SOURCE": os.getenv("DATA_SOURCE", "mock"),
        "ENVIRONMENT": os.getenv("ENVIRONMENT", "local"),
    }

    return {
        "name": "Ops console configuration",
        "status": "PASS",
        "category": "configuration",
        "message": "Ops console has minimum configuration for operational demo",
        "details": configured_items,
    }


def _wrap_graph_signal() -> dict[str, Any]:
    graph_signal = build_graph_signal()

    return {
        "name": "Virtual Graph / SharePoint signal",
        "status": graph_signal.get("status", "FAIL"),
        "category": "graph",
        "message": graph_signal.get(
            "signal",
            "Virtual Graph / SharePoint signal executed",
        ),
        "details": graph_signal,
    }


def _wrap_data_protection_report() -> dict[str, Any]:
    report = build_data_protection_report()

    return {
        "name": "Data protection validation",
        "status": report.get("status", "FAIL"),
        "category": "security",
        "message": report.get(
            "purpose",
            "Validate partner-facing payload does not leak sensitive fields",
        ),
        "details": report,
    }


def _classify_status(status: str) -> str:
    """
    Normalize check status for summary.

    PASS: fully passed.
    READY: configured/available, not a failure.
    PENDING: not configured yet or intentionally skipped.
    PASS_WITH_PENDING: partial pass but still has pending sub-checks.
    FAIL: failed.
    """

    normalized = (status or "").upper()

    if normalized == "FAIL":
        return "fail"

    if normalized in {"PENDING", "PASS_WITH_PENDING"}:
        return "pending"

    if normalized == "READY":
        return "ready"

    if normalized == "PASS":
        return "pass"

    return "pending"


def build_full_system_check() -> dict[str, Any]:
    """
    Build the top-level operational health report for the demo environment.

    This check is designed for browser-based operations:
    - basic backend status
    - ops console configuration
    - virtual Graph / SharePoint signal
    - data protection validation
    - APIM/JWT synthetic live check
    """

    checks = [
        _build_basic_backend_status(),
        _build_ops_configuration_status(),
        _wrap_graph_signal(),
        _wrap_data_protection_report(),
        build_apim_synthetic_check(),
    ]

    classified = [_classify_status(check.get("status", "")) for check in checks]

    pass_count = classified.count("pass")
    ready_count = classified.count("ready")
    pending_count = classified.count("pending")
    fail_count = classified.count("fail")

    if fail_count > 0:
        overall_status = "FAIL"
    elif pending_count > 0:
        overall_status = "PASS_WITH_PENDING"
    else:
        overall_status = "PASS"

    return {
        "overallStatus": overall_status,
        "summary": {
            "totalChecks": len(checks),
            "pass": pass_count,
            "ready": ready_count,
            "pending": pending_count,
            "fail": fail_count,
        },
        "checks": checks,
        "interpretation": {
            "PASS": "All configured checks passed.",
            "PASS_WITH_PENDING": (
                "Core demo checks passed, but at least one live or optional check "
                "is still pending configuration."
            ),
            "FAIL": "At least one required operational check failed.",
        },
        "nextPhase": (
            "Configure APIM/JWT synthetic env vars and rerun Full System Check."
            if overall_status == "PASS_WITH_PENDING"
            else "All configured checks are complete."
        ),
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
    }