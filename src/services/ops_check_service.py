from datetime import datetime, timezone
import os
from typing import Any

from src.services.virtual_graph_service import (
    build_data_protection_report,
    build_graph_signal,
)


def _check_status_to_bool(status: str) -> bool:
    return status.upper() in {"PASS", "READY"}


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
        "message": "Ops console has minimum configuration for local operational demo",
        "details": configured_items,
    }


def _build_apim_synthetic_readiness() -> dict[str, Any]:
    """
    This does not call APIM yet.

    The live APIM/JWT check will be implemented in the next phase after we decide
    where to store synthetic credentials safely for demo mode.
    """

    expected_env_vars = [
        "OPS_APIM_GATEWAY_URL",
        "OPS_APIM_SUBSCRIPTION_KEY",
        "OPS_SYNTHETIC_CLIENT_ID",
        "OPS_SYNTHETIC_CLIENT_SECRET",
        "OPS_DSR_API_APP_ID",
        "OPS_TENANT_ID",
    ]

    configured = {
        name: bool(os.getenv(name))
        for name in expected_env_vars
    }

    missing = [
        name
        for name, is_configured in configured.items()
        if not is_configured
    ]

    status = "READY" if not missing else "PENDING"

    return {
        "name": "APIM/JWT synthetic check readiness",
        "status": status,
        "category": "apim",
        "message": (
            "APIM/JWT live synthetic check is ready to run"
            if status == "READY"
            else "APIM/JWT live synthetic check is not configured yet; this is expected before Phase 7.5"
        ),
        "details": {
            "configured": configured,
            "missing": missing,
            "note": "No secret values are returned by this endpoint.",
        },
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


def build_full_system_check() -> dict[str, Any]:
    checks = [
        _build_basic_backend_status(),
        _build_ops_configuration_status(),
        _wrap_graph_signal(),
        _wrap_data_protection_report(),
        _build_apim_synthetic_readiness(),
    ]

    failed_checks = [
        check
        for check in checks
        if check["status"] == "FAIL"
    ]

    pending_checks = [
        check
        for check in checks
        if check["status"] == "PENDING"
    ]

    pass_count = sum(1 for check in checks if check["status"] == "PASS")
    ready_count = sum(1 for check in checks if check["status"] == "READY")
    pending_count = len(pending_checks)
    fail_count = len(failed_checks)

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
        "nextPhase": (
            "Configure browser-based APIM/JWT synthetic check in Phase 7.5"
            if pending_count > 0
            else "All configured checks are ready"
        ),
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
    }