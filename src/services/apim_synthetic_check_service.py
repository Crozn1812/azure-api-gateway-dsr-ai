from datetime import datetime, timezone
import os
import time
from typing import Any
from urllib.parse import urljoin

import requests


REQUIRED_APIM_SYNTHETIC_ENV_VARS = [
    "OPS_TENANT_ID",
    "OPS_DSR_API_APP_ID",
    "OPS_SYNTHETIC_CLIENT_ID",
    "OPS_SYNTHETIC_CLIENT_SECRET",
    "OPS_APIM_GATEWAY_URL",
    "OPS_APIM_SUBSCRIPTION_KEY",
]


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None

    value = value.strip()
    return value if value else None


def _configured_status() -> dict[str, Any]:
    configured = {
        name: bool(_get_env(name))
        for name in REQUIRED_APIM_SYNTHETIC_ENV_VARS
    }

    missing = [
        name
        for name, is_configured in configured.items()
        if not is_configured
    ]

    return {
        "configured": configured,
        "missing": missing,
        "isReady": len(missing) == 0,
    }


def _build_url(*parts: str) -> str:
    clean_parts = [
        str(part).strip("/")
        for part in parts
        if part is not None and str(part).strip("/")
    ]

    if not clean_parts:
        return ""

    base = clean_parts[0]
    rest = clean_parts[1:]

    url = base
    for part in rest:
        url = urljoin(url.rstrip("/") + "/", part)

    return url


def _safe_response_body(response: requests.Response, max_chars: int = 600) -> str:
    text = response.text or ""
    return text[:max_chars]


def _make_check(
    name: str,
    status: str,
    message: str,
    http_status: int | None = None,
    duration_ms: float | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "httpStatus": http_status,
        "durationMs": duration_ms,
        "details": details or {},
    }


def _acquire_access_token() -> tuple[str | None, dict[str, Any]]:
    tenant_id = _get_env("OPS_TENANT_ID")
    client_id = _get_env("OPS_SYNTHETIC_CLIENT_ID")
    client_secret = _get_env("OPS_SYNTHETIC_CLIENT_SECRET")
    dsr_api_app_id = _get_env("OPS_DSR_API_APP_ID")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    form_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": f"api://{dsr_api_app_id}/.default",
        "grant_type": "client_credentials",
    }

    start_time = time.time()

    try:
        response = requests.post(
            token_url,
            data=form_data,
            timeout=20,
        )

        duration_ms = round((time.time() - start_time) * 1000, 2)

        if response.status_code != 200:
            return None, _make_check(
                name="OAuth2 token acquisition",
                status="FAIL",
                message="Failed to acquire OAuth2 access token from Microsoft Entra ID",
                http_status=response.status_code,
                duration_ms=duration_ms,
                details={
                    "tokenEndpoint": token_url,
                    "responseSnippet": _safe_response_body(response),
                    "secretReturned": False,
                },
            )

        payload = response.json()
        access_token = payload.get("access_token")

        if not access_token:
            return None, _make_check(
                name="OAuth2 token acquisition",
                status="FAIL",
                message="Token endpoint returned 200 but access_token is missing",
                http_status=response.status_code,
                duration_ms=duration_ms,
                details={
                    "tokenEndpoint": token_url,
                    "secretReturned": False,
                },
            )

        return access_token, _make_check(
            name="OAuth2 token acquisition",
            status="PASS",
            message="Access token acquired using client credentials flow",
            http_status=response.status_code,
            duration_ms=duration_ms,
            details={
                "tokenEndpoint": token_url,
                "tokenType": payload.get("token_type"),
                "expiresIn": payload.get("expires_in"),
                "tokenReturned": True,
                "tokenValueHidden": True,
            },
        )

    except requests.RequestException as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)

        return None, _make_check(
            name="OAuth2 token acquisition",
            status="FAIL",
            message="Network or HTTP client error while acquiring token",
            duration_ms=duration_ms,
            details={
                "error": str(exc),
                "secretReturned": False,
            },
        )


def _call_apim_missing_token(apim_endpoint: str, apim_subscription_key: str) -> dict[str, Any]:
    start_time = time.time()

    try:
        response = requests.get(
            apim_endpoint,
            headers={
                "x-partner-id": "partner-a",
                "Ocp-Apim-Subscription-Key": apim_subscription_key,
            },
            timeout=20,
        )

        duration_ms = round((time.time() - start_time) * 1000, 2)

        expected = response.status_code == 401

        return _make_check(
            name="APIM missing token rejection",
            status="PASS" if expected else "FAIL",
            message=(
                "APIM correctly rejected request without Bearer token"
                if expected
                else "APIM did not return expected 401 for missing token"
            ),
            http_status=response.status_code,
            duration_ms=duration_ms,
            details={
                "expectedHttpStatus": 401,
                "endpoint": apim_endpoint,
                "responseSnippet": _safe_response_body(response),
            },
        )

    except requests.RequestException as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)

        return _make_check(
            name="APIM missing token rejection",
            status="FAIL",
            message="Network or HTTP client error while calling APIM without token",
            duration_ms=duration_ms,
            details={
                "endpoint": apim_endpoint,
                "error": str(exc),
            },
        )


def _call_apim_valid_token(
    apim_endpoint: str,
    apim_subscription_key: str,
    access_token: str,
) -> dict[str, Any]:
    start_time = time.time()

    try:
        response = requests.get(
            apim_endpoint,
            headers={
                "x-partner-id": "partner-a",
                "Ocp-Apim-Subscription-Key": apim_subscription_key,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=20,
        )

        duration_ms = round((time.time() - start_time) * 1000, 2)

        parsed_body: dict[str, Any] = {}
        try:
            parsed_body = response.json()
        except ValueError:
            parsed_body = {}

        has_correlation_id = "correlationId" in parsed_body
        has_data = isinstance(parsed_body.get("data"), list)
        has_expected_item = "DSR-2026-0001" in response.text

        expected = (
            response.status_code == 200
            and has_correlation_id
            and has_data
            and has_expected_item
        )

        return _make_check(
            name="APIM valid token data access",
            status="PASS" if expected else "FAIL",
            message=(
                "APIM accepted valid subscription key and JWT token, then returned DSR data"
                if expected
                else "APIM valid token call did not return expected DSR API response"
            ),
            http_status=response.status_code,
            duration_ms=duration_ms,
            details={
                "expectedHttpStatus": 200,
                "endpoint": apim_endpoint,
                "hasCorrelationId": has_correlation_id,
                "hasDataArray": has_data,
                "hasExpectedItem": has_expected_item,
                "itemCount": len(parsed_body.get("data", [])) if has_data else 0,
                "responseSnippet": _safe_response_body(response),
                "tokenValueHidden": True,
            },
        )

    except requests.RequestException as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)

        return _make_check(
            name="APIM valid token data access",
            status="FAIL",
            message="Network or HTTP client error while calling APIM with valid token",
            duration_ms=duration_ms,
            details={
                "endpoint": apim_endpoint,
                "error": str(exc),
                "tokenValueHidden": True,
            },
        )


def _call_backend_direct_protection() -> dict[str, Any]:
    backend_url = _get_env("OPS_BACKEND_URL")
    backend_api_key = _get_env("OPS_BACKEND_DIRECT_API_KEY", "demo-partner-key")

    if not backend_url:
        return _make_check(
            name="Backend direct protection",
            status="PENDING",
            message="OPS_BACKEND_URL is not configured, so backend direct protection check is skipped",
            details={
                "missing": ["OPS_BACKEND_URL"],
            },
        )

    endpoint = _build_url(backend_url, "partner/dsr/requests")
    start_time = time.time()

    try:
        response = requests.get(
            endpoint,
            headers={
                "x-partner-id": "partner-a",
                "x-api-key": backend_api_key,
            },
            timeout=20,
        )

        duration_ms = round((time.time() - start_time) * 1000, 2)

        expected = response.status_code == 403

        return _make_check(
            name="Backend direct protection",
            status="PASS" if expected else "FAIL",
            message=(
                "Backend direct call is blocked; request must go through API Gateway"
                if expected
                else "Backend direct call was not blocked as expected"
            ),
            http_status=response.status_code,
            duration_ms=duration_ms,
            details={
                "expectedHttpStatus": 403,
                "endpoint": endpoint,
                "responseSnippet": _safe_response_body(response),
            },
        )

    except requests.RequestException as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)

        return _make_check(
            name="Backend direct protection",
            status="FAIL",
            message="Network or HTTP client error while checking backend direct protection",
            duration_ms=duration_ms,
            details={
                "endpoint": endpoint,
                "error": str(exc),
            },
        )


def build_apim_synthetic_check() -> dict[str, Any]:
    readiness = _configured_status()

    if not readiness["isReady"]:
        return {
            "name": "APIM/JWT synthetic live check",
            "status": "PENDING",
            "category": "apim",
            "message": "APIM/JWT synthetic live check is not configured yet",
            "details": {
                "configured": readiness["configured"],
                "missing": readiness["missing"],
                "note": "No secret values are returned by this endpoint.",
            },
            "timestampUtc": datetime.now(timezone.utc).isoformat(),
        }

    apim_gateway_url = _get_env("OPS_APIM_GATEWAY_URL")
    api_path = _get_env("OPS_API_PATH", "partner-api")
    apim_subscription_key = _get_env("OPS_APIM_SUBSCRIPTION_KEY")

    apim_endpoint = _build_url(
        apim_gateway_url,
        api_path,
        "partner/dsr/requests",
    )

    checks: list[dict[str, Any]] = []

    checks.append(
        _call_apim_missing_token(
            apim_endpoint=apim_endpoint,
            apim_subscription_key=apim_subscription_key,
        )
    )

    access_token, token_check = _acquire_access_token()
    checks.append(token_check)

    if access_token:
        checks.append(
            _call_apim_valid_token(
                apim_endpoint=apim_endpoint,
                apim_subscription_key=apim_subscription_key,
                access_token=access_token,
            )
        )
    else:
        checks.append(
            _make_check(
                name="APIM valid token data access",
                status="FAIL",
                message="Skipped because token acquisition failed",
                details={
                    "tokenValueHidden": True,
                },
            )
        )

    checks.append(_call_backend_direct_protection())

    failed_checks = [
        check for check in checks
        if check["status"] == "FAIL"
    ]

    pending_checks = [
        check for check in checks
        if check["status"] == "PENDING"
    ]

    if failed_checks:
        overall_status = "FAIL"
    elif pending_checks:
        overall_status = "PASS_WITH_PENDING"
    else:
        overall_status = "PASS"

    return {
        "name": "APIM/JWT synthetic live check",
        "status": overall_status,
        "category": "apim",
        "message": (
            "APIM/JWT synthetic check completed"
            if overall_status != "FAIL"
            else "APIM/JWT synthetic check failed"
        ),
        "apimEndpoint": apim_endpoint,
        "summary": {
            "totalChecks": len(checks),
            "pass": sum(1 for check in checks if check["status"] == "PASS"),
            "pending": len(pending_checks),
            "fail": len(failed_checks),
        },
        "checks": checks,
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
    }