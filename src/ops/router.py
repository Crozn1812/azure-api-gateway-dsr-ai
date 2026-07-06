import inspect
import json
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from src.services import apim_synthetic_check_service
from src.services import ops_check_service
from src.services import virtual_graph_service


router = APIRouter()

REQUEST_HISTORY: Deque[Dict[str, Any]] = deque(maxlen=10)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DemoUrlVerifyRequest(BaseModel):
    partnerId: str = Field(..., examples=["partner-a"])
    demoUrl: str = Field(..., min_length=1, examples=["https://demo.partner-a.local/api"])


class DemoKeyVerifyRequest(BaseModel):
    partnerId: str = Field(..., examples=["partner-a"])
    demoUrl: str = Field(..., min_length=1)
    demoKey: str = Field(..., min_length=1, examples=["demo-key-a"])


class PartnerMatrixOpsRequest(BaseModel):
    partnerId: str = Field(..., examples=["partner-a"])
    requestedFields: List[str] = Field(..., examples=[["a", "b", "c"]])
    demoUrl: str | None = None
    demoKey: str | None = None


class PartnerGovernanceUpdateRequest(BaseModel):
    partnerId: str = Field(..., examples=["partner-a"])
    isActive: bool = True
    expiryDate: str = Field(..., examples=["2026-12-31"])
    quotaLimit: int = Field(..., ge=1, le=100000)


# ---------------------------------------------------------------------------
# Demo partner onboarding configuration
# These values are intentionally fake and are used only by the simulator UI.
# Real APIM/Entra credentials remain server-side.
# ---------------------------------------------------------------------------

DEMO_PARTNER_ACCESS: Dict[str, Dict[str, str]] = {
    "partner-a": {
        "url": "https://demo.partner-a.local/api",
        "key": "demo-key-a",
    },
    "partner-b": {
        "url": "https://demo.partner-b.local/api",
        "key": "demo-key-b",
    },
    "partner-c": {
        "url": "https://demo.partner-c.local/api",
        "key": "demo-key-c",
    },
    "partner-d": {
        "url": "https://demo.partner-d.local/api",
        "key": "demo-key-d",
    },
    "partner-e": {
        "url": "https://demo.partner-e.local/api",
        "key": "demo-key-e",
    },
    "partner-f": {
        "url": "https://demo.partner-f.local/api",
        "key": "demo-key-f",
    },
    "partner-g": {
        "url": "https://demo.partner-g.local/api",
        "key": "demo-key-g",
    },
}


PARTNER_GOVERNANCE_STATE: Dict[str, Dict[str, Any]] = {
    partner_id: {
        "isActive": True,
        "expiryDate": "2026-12-31",
        "quotaLimit": 100,
        "quotaUsed": 0,
    }
    for partner_id in DEMO_PARTNER_ACCESS
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def require_ops_key(key: str | None) -> None:
    expected_key = os.getenv("OPS_CONSOLE_KEY", "demo-ops-key")

    if not expected_key:
        raise HTTPException(
            status_code=403,
            detail="Ops console key is not configured.",
        )

    if key != expected_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid ops console key.",
        )


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def call_service_function(module: Any, candidate_names: List[str]) -> Any:
    for name in candidate_names:
        func = getattr(module, name, None)
        if callable(func):
            return await maybe_await(func())

    raise HTTPException(
        status_code=500,
        detail=f"Service function not found. Tried: {', '.join(candidate_names)}",
    )


def clean_url_join(base: str, path: str, suffix: str) -> str:
    return f"{base.rstrip('/')}/{path.strip('/')}/{suffix.lstrip('/')}"


def normalize_partner_id(partner_id: str) -> str:
    return partner_id.strip().lower()


def load_partner_access_matrix() -> Dict[str, Any]:
    matrix_path = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "partner_access_matrix.json"
    )

    try:
        with matrix_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="Partner access matrix file was not found.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail="Partner access matrix contains invalid JSON.",
        ) from exc

    # Supports either:
    # {"partner-a": {...}}
    # or {"partners": {"partner-a": {...}}}
    partners = data.get("partners") if isinstance(data, dict) else None
    return partners if isinstance(partners, dict) else data


def get_partner_profile(partner_id: str) -> Dict[str, Any]:
    normalized = normalize_partner_id(partner_id)
    matrix = load_partner_access_matrix()
    profile = matrix.get(normalized) if isinstance(matrix, dict) else None

    if not isinstance(profile, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Partner profile not found: {normalized}",
        )

    allowed_fields = profile.get("allowedFields", [])
    if not isinstance(allowed_fields, list):
        raise HTTPException(
            status_code=500,
            detail=f"Invalid allowedFields configuration for {normalized}.",
        )

    return profile



def get_partner_governance(partner_id: str) -> Dict[str, Any]:
    normalized = normalize_partner_id(partner_id)
    state = PARTNER_GOVERNANCE_STATE.get(normalized)

    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"Governance profile not found: {normalized}",
        )

    return state


def validate_partner_governance(partner_id: str) -> Dict[str, Any]:
    normalized = normalize_partner_id(partner_id)
    state = get_partner_governance(normalized)

    if not state.get("isActive", False):
        raise HTTPException(
            status_code=403,
            detail="Partner access is disabled.",
        )

    try:
        expiry_date = datetime.strptime(
            str(state.get("expiryDate")),
            "%Y-%m-%d",
        ).date()
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid expiryDate for {normalized}.",
        ) from exc

    if expiry_date < datetime.now(timezone.utc).date():
        raise HTTPException(
            status_code=403,
            detail="Partner access has expired.",
        )

    quota_limit = int(state.get("quotaLimit", 0))
    quota_used = int(state.get("quotaUsed", 0))

    if quota_used >= quota_limit:
        raise HTTPException(
            status_code=429,
            detail="Partner quota has been exhausted.",
        )

    return state


def build_governance_response(partner_id: str) -> Dict[str, Any]:
    normalized = normalize_partner_id(partner_id)
    state = get_partner_governance(normalized)

    quota_limit = int(state.get("quotaLimit", 0))
    quota_used = int(state.get("quotaUsed", 0))

    return {
        "partnerId": normalized,
        "isActive": bool(state.get("isActive", False)),
        "expiryDate": state.get("expiryDate"),
        "quotaLimit": quota_limit,
        "quotaUsed": quota_used,
        "quotaRemaining": max(quota_limit - quota_used, 0),
    }


def validate_demo_url(partner_id: str, demo_url: str) -> Dict[str, str]:
    normalized = normalize_partner_id(partner_id)
    config = DEMO_PARTNER_ACCESS.get(normalized)

    if not config:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported partner: {normalized}",
        )

    if demo_url.strip() != config["url"]:
        raise HTTPException(
            status_code=401,
            detail="Demo URL is not valid for the selected partner.",
        )

    return config


def validate_demo_key(
    partner_id: str,
    demo_url: str,
    demo_key: str,
) -> Dict[str, str]:
    config = validate_demo_url(partner_id, demo_url)

    if demo_key.strip() != config["key"]:
        raise HTTPException(
            status_code=401,
            detail="Demo partner key is invalid.",
        )

    return config


def get_partner_gateway_credentials(partner_id: str) -> Dict[str, str]:
    normalized = normalize_partner_id(partner_id)

    real_mapping: Dict[str, Dict[str, str | None]] = {
        "partner-a": {
            "client_id": os.getenv("PARTNER_A_CLIENT_ID")
            or os.getenv("OPS_SYNTHETIC_CLIENT_ID"),
            "client_secret": os.getenv("PARTNER_A_CLIENT_SECRET")
            or os.getenv("OPS_SYNTHETIC_CLIENT_SECRET"),
            "apim_key": os.getenv("PARTNER_A_APIM_KEY")
            or os.getenv("OPS_APIM_SUBSCRIPTION_KEY"),
        },
        "partner-b": {
            "client_id": os.getenv("PARTNER_B_CLIENT_ID"),
            "client_secret": os.getenv("PARTNER_B_CLIENT_SECRET"),
            "apim_key": os.getenv("PARTNER_B_APIM_KEY"),
        },
    }

    if normalized in {"partner-c", "partner-d", "partner-e", "partner-f", "partner-g"}:
        # C-G are simulated partner profiles. They reuse Partner A's server-side
        # credential while retaining separate field-level access profiles.
        credentials = real_mapping["partner-a"]
    else:
        credentials = real_mapping.get(normalized)

    if not credentials:
        raise HTTPException(
            status_code=400,
            detail=f"No APIM/Entra credential mapping for {normalized}.",
        )

    missing = [
        name
        for name, value in credentials.items()
        if not value
    ]

    if missing:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Missing server-side credential for {normalized}: "
                f"{', '.join(missing)}"
            ),
        )

    return {
        "client_id": str(credentials["client_id"]),
        "client_secret": str(credentials["client_secret"]),
        "apim_key": str(credentials["apim_key"]),
    }


async def get_partner_access_token(
    client_id: str,
    client_secret: str,
) -> str:
    tenant_id = os.getenv("TENANT_ID") or os.getenv("OPS_TENANT_ID")
    api_app_id = os.getenv("DSR_API_APP_ID") or os.getenv("OPS_DSR_API_APP_ID")

    missing = [
        name
        for name, value in {
            "TENANT_ID": tenant_id,
            "DSR_API_APP_ID": api_app_id,
            "CLIENT_ID": client_id,
            "CLIENT_SECRET": client_secret,
        }.items()
        if not value
    ]

    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Entra configuration: {', '.join(missing)}",
        )

    token_url = (
        f"https://login.microsoftonline.com/"
        f"{tenant_id}/oauth2/v2.0/token"
    )

    token_payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": f"api://{api_app_id}/.default",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(token_url, data=token_payload)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to acquire Entra ID access token.",
                "statusCode": response.status_code,
                "response": response.text[:500],
            },
        )

    access_token = response.json().get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="Token response does not contain access_token.",
        )

    return access_token



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_request_history(entry: Dict[str, Any]) -> None:
    REQUEST_HISTORY.appendleft(entry)


def get_request_history_snapshot() -> List[Dict[str, Any]]:
    return list(REQUEST_HISTORY)


async def call_partner_matrix_via_apim(
    payload: PartnerMatrixOpsRequest,
) -> Dict[str, Any]:
    partner_id = normalize_partner_id(payload.partnerId)
    governance = validate_partner_governance(partner_id)
    correlation_id = str(uuid.uuid4())
    started_at = time.perf_counter()
    timestamp = utc_now_iso()

    # When the request originates from the staged UI, verify the demo URL/key
    # again server-side. Frontend state is not security, merely optimism.
    if payload.demoUrl is not None or payload.demoKey is not None:
        if not payload.demoUrl or not payload.demoKey:
            raise HTTPException(
                status_code=401,
                detail="Both demoUrl and demoKey are required.",
            )
        validate_demo_key(partner_id, payload.demoUrl, payload.demoKey)

    credentials = get_partner_gateway_credentials(partner_id)

    apim_gateway = (
        os.getenv("APIM_GATEWAY")
        or os.getenv("OPS_APIM_GATEWAY_URL")
    )
    api_path = (
        os.getenv("API_PATH")
        or os.getenv("OPS_API_PATH")
        or "partner-api"
    )

    if not apim_gateway:
        raise HTTPException(
            status_code=500,
            detail="APIM gateway URL is not configured.",
        )

    access_token = await get_partner_access_token(
        credentials["client_id"],
        credentials["client_secret"],
    )

    endpoint = clean_url_join(
        apim_gateway,
        api_path,
        "/partner/dsr/matrix-request",
    )

    headers = {
        "Content-Type": "application/json",
        "x-partner-id": partner_id,
        "x-correlation-id": correlation_id,
        "Ocp-Apim-Subscription-Key": credentials["apim_key"],
        "Authorization": f"Bearer {access_token}",
    }

    request_body = {
        "partnerId": partner_id,
        "requestedFields": payload.requestedFields,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            endpoint,
            headers=headers,
            json=request_body,
        )

    try:
        response_body = response.json()
    except Exception:
        response_body = {"rawResponse": response.text}

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    policy_status = (
        response_body.get("status", "UNKNOWN")
        if isinstance(response_body, dict)
        else "UNKNOWN"
    )

    governance["quotaUsed"] = int(governance.get("quotaUsed", 0)) + 1

    history_entry = {
        "timestamp": timestamp,
        "correlationId": correlation_id,
        "partnerId": partner_id,
        "requestedFields": payload.requestedFields,
        "policyStatus": policy_status,
        "httpStatusCode": response.status_code,
        "durationMs": duration_ms,
        "operation": "POST /partner/dsr/matrix-request",
    }
    add_request_history(history_entry)

    return {
        "timestamp": timestamp,
        "correlationId": correlation_id,
        "durationMs": duration_ms,
        "governance": build_governance_response(partner_id),
        "apimRoute": {
            "gatewayUrl": apim_gateway,
            "apiPath": api_path,
            "operation": "POST /partner/dsr/matrix-request",
            "calledThroughApim": True,
            "apimLogged": True,
        },
        "httpStatusCode": response.status_code,
        "result": response_body,
    }


# ---------------------------------------------------------------------------
# Ops Console HTML
# ---------------------------------------------------------------------------

OPS_CONSOLE_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DSR API Gateway Ops Console</title>
    <style>
        body {
            background: #0f172a;
            color: #f8fafc;
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 24px;
        }

        .container {
            max-width: 1180px;
            margin: auto;
        }

        .card {
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            background: #111827;
        }

        .step-card {
            border-left: 4px solid #2563eb;
        }

        .hidden {
            display: none;
        }

        h1, h2, h3 {
            margin-top: 0;
        }

        .muted {
            color: #93c5fd;
            font-size: 14px;
        }

        .status {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 999px;
            background: #047857;
            color: white;
            font-weight: bold;
            font-size: 13px;
        }

        .step-number {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: #2563eb;
            font-weight: bold;
            margin-right: 8px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }

        th, td {
            border-bottom: 1px solid #334155;
            padding: 10px;
            text-align: left;
            font-size: 14px;
        }

        th {
            color: #93c5fd;
        }

        .pass {
            color: #22c55e;
            font-weight: bold;
        }

        .warn {
            color: #facc15;
            font-weight: bold;
        }

        .fail {
            color: #ef4444;
            font-weight: bold;
        }

        button {
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 7px;
            padding: 10px 14px;
            margin: 6px 6px 6px 0;
            cursor: pointer;
            font-weight: bold;
        }

        button:hover {
            background: #1d4ed8;
        }

        button:disabled {
            background: #475569;
            cursor: not-allowed;
        }

        .button-green {
            background: #16a34a;
        }

        .button-green:hover {
            background: #15803d;
        }

        .button-purple {
            background: #7c3aed;
        }

        .button-purple:hover {
            background: #6d28d9;
        }

        input, select {
            width: 100%;
            box-sizing: border-box;
            background: #020617;
            color: #f8fafc;
            border: 1px solid #475569;
            border-radius: 6px;
            padding: 10px;
            margin: 6px 0 12px 0;
        }

        label {
            font-weight: bold;
            font-size: 14px;
            color: #bfdbfe;
        }

        pre, .result-box {
            background: #020617;
            border: 1px solid #475569;
            border-radius: 8px;
            padding: 14px;
            min-height: 80px;
            overflow: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
        }

        .badge {
            display: inline-block;
            padding: 4px 9px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: bold;
        }

        .badge-pass {
            background: #064e3b;
            color: #6ee7b7;
        }

        .badge-fail {
            background: #7f1d1d;
            color: #fecaca;
        }

        .badge-warn {
            background: #713f12;
            color: #fde68a;
        }

        .field-chip {
            display: inline-block;
            background: #1e3a8a;
            color: #dbeafe;
            padding: 5px 9px;
            border-radius: 999px;
            margin: 3px;
            font-size: 13px;
        }

        .scope-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
            margin: 12px 0 18px 0;
        }

        .scope-item {
            display: flex;
            align-items: flex-start;
            gap: 9px;
            background: #020617;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 11px;
        }

        .scope-item input {
            width: auto;
            margin: 2px 0 0 0;
        }

        .scope-name {
            font-weight: bold;
            color: #dbeafe;
        }

        .scope-description {
            display: block;
            color: #94a3b8;
            font-size: 12px;
            margin-top: 3px;
        }

        .history-scroll {
            overflow-x: auto;
        }

        .mono {
            font-family: Consolas, monospace;
            font-size: 12px;
        }


        .admin-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 14px;
        }

        .admin-grid .full-width {
            grid-column: 1 / -1;
        }

        @media (max-width: 760px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <h1>DSR API Gateway Ops Console</h1>
        <p class="muted">
            Staged partner onboarding simulator: URL verification, demo key verification,
            then APIM-backed data request.
        </p>
        <span class="status">OPS CONSOLE ONLINE</span>
    </div>

    <div class="card">
        <h2>Operational Checks</h2>
        <button class="button-green" onclick="runCheck('full-check')">Run Full System Check</button>
        <button class="button-purple" onclick="runCheck('apim-synthetic')">Run APIM/JWT Synthetic Check</button>
        <button onclick="runCheck('status')">Run Basic Status Check</button>
        <button onclick="runCheck('graph-signal')">Run Virtual Graph Signal</button>
        <button onclick="runCheck('data-protection')">Run Data Protection Check</button>
        <pre id="opsResult">Ops Console UI loaded. Run a check.</pre>
    </div>

    <div class="card step-card">
        <h2><span class="step-number">1</span>Verify Demo URL</h2>
        <p class="muted">
            Select a partner and enter its fake onboarding URL. The URL is validated only
            against the simulator configuration and is never called by the backend.
        </p>

        <div class="grid">
            <div>
                <label for="partnerId">Partner ID</label>
                <select id="partnerId" onchange="resetFlow()">
                    <option value="partner-a">partner-a</option>
                    <option value="partner-b">partner-b</option>
                    <option value="partner-c">partner-c</option>
                    <option value="partner-d">partner-d</option>
                    <option value="partner-e">partner-e</option>
                    <option value="partner-f">partner-f</option>
                    <option value="partner-g">partner-g</option>
                </select>
            </div>

            <div>
                <label for="demoUrl">Demo URL</label>
                <input
                    id="demoUrl"
                    value="https://demo.partner-a.local/api"
                    placeholder="https://demo.partner-a.local/api"
                >
            </div>
        </div>

        <button onclick="verifyDemoUrl()">Verify URL</button>
        <button onclick="fillDemoUrl()">Fill Example URL</button>

        <div id="urlResult" class="result-box">URL has not been verified.</div>
    </div>

    <div id="keyStep" class="card step-card hidden">
        <h2><span class="step-number">2</span>Verify Demo Partner Key</h2>
        <p class="muted">
            Enter the fake key assigned to the selected partner. Real APIM keys and Entra
            secrets remain server-side.
        </p>

        <label for="demoKey">Demo Partner Key</label>
        <input
            id="demoKey"
            type="password"
            placeholder="Example: demo-key-a"
            autocomplete="off"
        >

        <button onclick="verifyDemoKey()">Verify Key</button>
        <button onclick="fillDemoKey()">Fill Example Key</button>

        <div id="keyResult" class="result-box">Key has not been verified.</div>
    </div>

    <div id="requestStep" class="card step-card hidden">
        <h2><span class="step-number">3</span>Request Partner Data</h2>

        <div id="partnerProfile" class="result-box"></div>

        <h3>Allowed Scope Discovery</h3>
        <p class="muted">
            Only fields granted to this partner are selectable. The backend still validates
            the final request independently.
        </p>

        <div id="scopeCheckboxes" class="scope-grid"></div>

        <label for="extraTestField">Optional policy test field</label>
        <input
            id="extraTestField"
            value=""
            placeholder="Example: internalNote"
        >

        <button class="button-green" onclick="runPartnerMatrixRequest()">Send Request via APIM</button>
        <button onclick="selectAllAllowedFields()">Select All Allowed</button>
        <button onclick="clearAllowedFields()">Clear Selection</button>
        <button onclick="setSensitiveExample()">Test internalNote</button>

        <div id="partnerMatrixResult" class="result-box">
            Partner Matrix result will appear here.
        </div>
    </div>

    <div class="card">
        <h2>Partner Governance Simulator</h2>
        <p class="muted">
            Simulates partner enable/disable, access expiry and request quota.
            Changes are temporary and reset when the app restarts.
        </p>

        <div class="admin-grid">
            <div>
                <label for="adminPartnerId">Partner</label>
                <select id="adminPartnerId" onchange="loadGovernanceProfile()">
                    <option value="partner-a">partner-a</option>
                    <option value="partner-b">partner-b</option>
                    <option value="partner-c">partner-c</option>
                    <option value="partner-d">partner-d</option>
                    <option value="partner-e">partner-e</option>
                    <option value="partner-f">partner-f</option>
                    <option value="partner-g">partner-g</option>
                </select>
            </div>

            <div>
                <label for="adminActive">Access Status</label>
                <select id="adminActive">
                    <option value="true">Active</option>
                    <option value="false">Disabled</option>
                </select>
            </div>

            <div>
                <label for="adminExpiry">Expiry Date</label>
                <input id="adminExpiry" type="date" value="2026-12-31">
            </div>

            <div>
                <label for="adminQuota">Quota Limit</label>
                <input id="adminQuota" type="number" min="1" value="100">
            </div>

            <div class="full-width">
                <button onclick="loadGovernanceProfile()">Load Profile</button>
                <button class="button-green" onclick="saveGovernanceProfile()">Save Governance</button>
            </div>
        </div>

        <div id="governanceResult" class="result-box">
            Governance profile has not been loaded.
        </div>
    </div>

    <div class="card">
        <h2>Recent Request History</h2>
        <p class="muted">
            Shows the latest 10 requests stored in this running app instance.
            Restarting the app clears this temporary history.
        </p>
        <button onclick="loadRequestHistory()">Refresh History</button>
        <div id="requestHistory" class="history-scroll result-box">
            No request history loaded.
        </div>
    </div>
</div>

<script>
    const params = new URLSearchParams(window.location.search);
    const opsKey = params.get("key") || "";

    let verifiedDemoUrl = "";
    let verifiedDemoKey = "";
    let verifiedPartnerId = "";
    let allowedFields = [];

    const fieldDescriptions = {
        "a": "Môn toán",
        "b": "Môn lý",
        "c": "Môn hóa",
        "d": "Môn sinh",
        "e": "Môn văn",
        "f": "Môn anh",
        "1": "Data value 1",
        "2": "Data value 2",
        "3": "Data value 3",
        "4": "Data value 4",
        "5": "Data value 5",
        "6": "Data value 6",
        "AB": "Classification AB",
        "AC": "Classification AC",
        "AD": "Classification AD",
        "AE": "Classification AE",
        "AF": "Classification AF"
    };

    const demoConfig = {
        "partner-a": {
            url: "https://demo.partner-a.local/api",
            key: "demo-key-a"
        },
        "partner-b": {
            url: "https://demo.partner-b.local/api",
            key: "demo-key-b"
        },
        "partner-c": {
            url: "https://demo.partner-c.local/api",
            key: "demo-key-c"
        },
        "partner-d": {
            url: "https://demo.partner-d.local/api",
            key: "demo-key-d"
        },
        "partner-e": {
            url: "https://demo.partner-e.local/api",
            key: "demo-key-e"
        },
        "partner-f": {
            url: "https://demo.partner-f.local/api",
            key: "demo-key-f"
        },
        "partner-g": {
            url: "https://demo.partner-g.local/api",
            key: "demo-key-g"
        }
    };

    function escapeHtml(value) {
        if (value === null || value === undefined) {
            return "";
        }

        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function getSelectedPartner() {
        return document.getElementById("partnerId").value.trim();
    }

    function resetFlow() {
        verifiedDemoUrl = "";
        verifiedDemoKey = "";
        verifiedPartnerId = "";
        allowedFields = [];

        document.getElementById("keyStep").classList.add("hidden");
        document.getElementById("requestStep").classList.add("hidden");
        document.getElementById("demoKey").value = "";
        document.getElementById("extraTestField").value = "";
        document.getElementById("scopeCheckboxes").innerHTML = "";
        document.getElementById("urlResult").textContent = "URL has not been verified.";
        document.getElementById("keyResult").textContent = "Key has not been verified.";
        document.getElementById("partnerMatrixResult").textContent =
            "Partner Matrix result will appear here.";

        fillDemoUrl();
    }

    function fillDemoUrl() {
        const partnerId = getSelectedPartner();
        document.getElementById("demoUrl").value = demoConfig[partnerId].url;
    }

    function fillDemoKey() {
        const partnerId = getSelectedPartner();
        document.getElementById("demoKey").value = demoConfig[partnerId].key;
    }

    function renderScopeCheckboxes(fields) {
        const container = document.getElementById("scopeCheckboxes");

        container.innerHTML = fields.map(field => {
            const description = fieldDescriptions[field] || "Approved partner field";

            return `
                <label class="scope-item">
                    <input
                        type="checkbox"
                        class="allowed-field-checkbox"
                        value="${escapeHtml(field)}"
                    >
                    <span>
                        <span class="scope-name">${escapeHtml(field)}</span>
                        <span class="scope-description">${escapeHtml(description)}</span>
                    </span>
                </label>
            `;
        }).join("");
    }

    function getSelectedAllowedFields() {
        return Array.from(
            document.querySelectorAll(".allowed-field-checkbox:checked")
        ).map(item => item.value);
    }

    function selectAllAllowedFields() {
        document
            .querySelectorAll(".allowed-field-checkbox")
            .forEach(item => {
                item.checked = true;
            });
    }

    function clearAllowedFields() {
        document
            .querySelectorAll(".allowed-field-checkbox")
            .forEach(item => {
                item.checked = false;
            });

        document.getElementById("extraTestField").value = "";
    }

    function setSensitiveExample() {
        clearAllowedFields();

        document
            .querySelectorAll(".allowed-field-checkbox")
            .forEach((item, index) => {
                item.checked = index < 2;
            });

        document.getElementById("extraTestField").value = "internalNote";
    }

    async function runCheck(checkName) {
        const resultBox = document.getElementById("opsResult");
        resultBox.textContent = `Running /ops/api/${checkName} ...`;

        try {
            const response = await fetch(
                `/ops/api/${checkName}?key=${encodeURIComponent(opsKey)}`
            );
            const data = await response.json();
            resultBox.textContent = JSON.stringify(data, null, 2);
        } catch (error) {
            resultBox.textContent = `ERROR: ${error}`;
        }
    }

    async function verifyDemoUrl() {
        const partnerId = getSelectedPartner();
        const demoUrl = document.getElementById("demoUrl").value.trim();
        const resultBox = document.getElementById("urlResult");

        document.getElementById("keyStep").classList.add("hidden");
        document.getElementById("requestStep").classList.add("hidden");

        resultBox.textContent = "Verifying demo URL...";

        try {
            const response = await fetch(
                `/ops/api/partner-access/verify-url?key=${encodeURIComponent(opsKey)}`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        partnerId: partnerId,
                        demoUrl: demoUrl
                    })
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    typeof data.detail === "string"
                        ? data.detail
                        : JSON.stringify(data.detail)
                );
            }

            verifiedPartnerId = partnerId;
            verifiedDemoUrl = demoUrl;
            verifiedDemoKey = "";

            resultBox.innerHTML = `
                <p class="pass">URL VERIFIED</p>
                <p><b>Partner:</b> ${escapeHtml(data.partnerId)}</p>
                <p><b>URL:</b> ${escapeHtml(data.demoUrl)}</p>
                <p><b>Mode:</b> ${escapeHtml(data.mode)}</p>
            `;

            document.getElementById("keyStep").classList.remove("hidden");
            document.getElementById("demoKey").focus();
        } catch (error) {
            resultBox.innerHTML = `<p class="fail">URL DENIED: ${escapeHtml(error.message)}</p>`;
        }
    }

    async function verifyDemoKey() {
        const partnerId = getSelectedPartner();
        const demoKey = document.getElementById("demoKey").value.trim();
        const resultBox = document.getElementById("keyResult");

        if (!verifiedDemoUrl || verifiedPartnerId !== partnerId) {
            resultBox.innerHTML = `<p class="fail">Verify the URL first.</p>`;
            return;
        }

        resultBox.textContent = "Verifying demo partner key...";

        try {
            const response = await fetch(
                `/ops/api/partner-access/verify-key?key=${encodeURIComponent(opsKey)}`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        partnerId: partnerId,
                        demoUrl: verifiedDemoUrl,
                        demoKey: demoKey
                    })
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    typeof data.detail === "string"
                        ? data.detail
                        : JSON.stringify(data.detail)
                );
            }

            verifiedDemoKey = demoKey;
            allowedFields = data.allowedFields || [];

            resultBox.innerHTML = `
                <p class="pass">KEY VERIFIED</p>
                <p><b>Partner:</b> ${escapeHtml(data.partnerId)}</p>
                <p><b>Credential Mode:</b> ${escapeHtml(data.credentialMode)}</p>
                <p><b>Gateway Mode:</b> ${escapeHtml(data.gatewayMode)}</p>
                <p><b>Quota Remaining:</b> ${escapeHtml(data.governance?.quotaRemaining)}</p>
                <p><b>Expiry Date:</b> ${escapeHtml(data.governance?.expiryDate)}</p>
            `;

            const chips = allowedFields
                .map(field => `<span class="field-chip">${escapeHtml(field)}</span>`)
                .join("");

            document.getElementById("partnerProfile").innerHTML = `
                <h3>Partner Access Profile</h3>
                <p><b>Partner:</b> ${escapeHtml(data.displayName || data.partnerId)}</p>
                <p><b>Status:</b> <span class="badge badge-pass">ACTIVE</span></p>
                <p><b>Expiry:</b> ${escapeHtml(data.governance?.expiryDate)}</p>
                <p><b>Quota Remaining:</b> ${escapeHtml(data.governance?.quotaRemaining)}</p>
                <p><b>Allowed Fields:</b></p>
                <div>${chips}</div>
            `;

            renderScopeCheckboxes(allowedFields);
            selectAllAllowedFields();
            document.getElementById("extraTestField").value = "";
            document.getElementById("requestStep").classList.remove("hidden");
        } catch (error) {
            verifiedDemoKey = "";
            allowedFields = [];
            document.getElementById("requestStep").classList.add("hidden");
            resultBox.innerHTML = `<p class="fail">KEY DENIED: ${escapeHtml(error.message)}</p>`;
        }
    }

    function renderPartnerMatrixResult(data) {
        const result = data.result || {};
        const status = result.status || "UNKNOWN";
        const policyMessage = result.policyMessage || result.message || "";
        const route = data.apimRoute || {};
        const statusClass = status === "ALLOWED" ? "badge-pass" : "badge-fail";

        let html = `
            <h3>
                Policy Result:
                <span class="badge ${statusClass}">${escapeHtml(status)}</span>
            </h3>

            <p><b>Message:</b> ${escapeHtml(policyMessage)}</p>

            <table>
                <tr><th>Gateway Item</th><th>Value</th></tr>
                <tr><td>Called Through APIM</td><td>${escapeHtml(route.calledThroughApim)}</td></tr>
                <tr><td>APIM Logged</td><td>${escapeHtml(route.apimLogged)}</td></tr>
                <tr><td>Operation</td><td>${escapeHtml(route.operation)}</td></tr>
                <tr><td>HTTP Status Code</td><td>${escapeHtml(data.httpStatusCode)}</td></tr>
                <tr><td>Correlation ID</td><td class="mono">${escapeHtml(data.correlationId)}</td></tr>
                <tr><td>Timestamp</td><td>${escapeHtml(data.timestamp)}</td></tr>
                <tr><td>Duration</td><td>${escapeHtml(data.durationMs)} ms</td></tr>
                <tr><td>Quota Remaining</td><td>${escapeHtml(data.governance?.quotaRemaining)}</td></tr>
            </table>
        `;

        if (result.requestJourney && result.requestJourney.length > 0) {
            html += `
                <h3>Request Journey</h3>
                <table>
                    <tr><th>Step</th><th>Description</th></tr>
            `;

            result.requestJourney.forEach((step, index) => {
                html += `
                    <tr>
                        <td>${index + 1}</td>
                        <td>${escapeHtml(step)}</td>
                    </tr>
                `;
            });

            html += `</table>`;
        }

        if (result.allowedData && result.allowedData.length > 0) {
            html += `
                <h3>Returned Data</h3>
                <table>
                    <tr><th>Field</th><th>Value</th><th>Status</th></tr>
            `;

            result.allowedData.forEach(item => {
                html += `
                    <tr>
                        <td>${escapeHtml(item.field)}</td>
                        <td>${escapeHtml(item.value)}</td>
                        <td class="pass">${escapeHtml(item.status)}</td>
                    </tr>
                `;
            });

            html += `</table>`;
        }

        if (result.deniedFields && result.deniedFields.length > 0) {
            html += `
                <h3>Denied Fields</h3>
                <p class="fail">${escapeHtml(result.deniedFields.join(", "))}</p>
            `;
        }

        if (result.sensitiveViolations && result.sensitiveViolations.length > 0) {
            html += `
                <h3>Sensitive Violations</h3>
                <p class="fail">${escapeHtml(result.sensitiveViolations.join(", "))}</p>
            `;
        }

        return html;
    }

    function renderGovernanceProfile(data) {
        return `
            <table>
                <tr><th>Item</th><th>Value</th></tr>
                <tr><td>Partner</td><td>${escapeHtml(data.partnerId)}</td></tr>
                <tr><td>Active</td><td>${escapeHtml(data.isActive)}</td></tr>
                <tr><td>Expiry Date</td><td>${escapeHtml(data.expiryDate)}</td></tr>
                <tr><td>Quota Limit</td><td>${escapeHtml(data.quotaLimit)}</td></tr>
                <tr><td>Quota Used</td><td>${escapeHtml(data.quotaUsed)}</td></tr>
                <tr><td>Quota Remaining</td><td>${escapeHtml(data.quotaRemaining)}</td></tr>
            </table>
        `;
    }

    async function loadGovernanceProfile() {
        const partnerId = document.getElementById("adminPartnerId").value;
        const resultBox = document.getElementById("governanceResult");

        resultBox.textContent = "Loading governance profile...";

        try {
            const response = await fetch(
                `/ops/api/partner-governance/${encodeURIComponent(partnerId)}?key=${encodeURIComponent(opsKey)}`
            );
            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    typeof data.detail === "string"
                        ? data.detail
                        : JSON.stringify(data.detail)
                );
            }

            document.getElementById("adminActive").value = String(data.isActive);
            document.getElementById("adminExpiry").value = data.expiryDate;
            document.getElementById("adminQuota").value = data.quotaLimit;
            resultBox.innerHTML = renderGovernanceProfile(data);
        } catch (error) {
            resultBox.innerHTML = `
                <p class="fail">GOVERNANCE ERROR: ${escapeHtml(error.message)}</p>
            `;
        }
    }

    async function saveGovernanceProfile() {
        const partnerId = document.getElementById("adminPartnerId").value;
        const isActive = document.getElementById("adminActive").value === "true";
        const expiryDate = document.getElementById("adminExpiry").value;
        const quotaLimit = Number(document.getElementById("adminQuota").value);
        const resultBox = document.getElementById("governanceResult");

        resultBox.textContent = "Saving governance profile...";

        try {
            const response = await fetch(
                `/ops/api/partner-governance?key=${encodeURIComponent(opsKey)}`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        partnerId: partnerId,
                        isActive: isActive,
                        expiryDate: expiryDate,
                        quotaLimit: quotaLimit
                    })
                }
            );
            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    typeof data.detail === "string"
                        ? data.detail
                        : JSON.stringify(data.detail)
                );
            }

            resultBox.innerHTML = `
                <p class="pass">GOVERNANCE UPDATED</p>
                ${renderGovernanceProfile(data)}
            `;
        } catch (error) {
            resultBox.innerHTML = `
                <p class="fail">SAVE ERROR: ${escapeHtml(error.message)}</p>
            `;
        }
    }

    function renderRequestHistory(items) {
        if (!items || items.length === 0) {
            return "<p class='muted'>No requests recorded in this app instance.</p>";
        }

        let html = `
            <table>
                <tr>
                    <th>Time</th>
                    <th>Partner</th>
                    <th>Fields</th>
                    <th>Result</th>
                    <th>HTTP</th>
                    <th>Duration</th>
                    <th>Correlation ID</th>
                </tr>
        `;

        items.forEach(item => {
            const resultClass =
                item.policyStatus === "ALLOWED" ? "pass" : "fail";

            html += `
                <tr>
                    <td>${escapeHtml(item.timestamp)}</td>
                    <td>${escapeHtml(item.partnerId)}</td>
                    <td>${escapeHtml((item.requestedFields || []).join(", "))}</td>
                    <td class="${resultClass}">${escapeHtml(item.policyStatus)}</td>
                    <td>${escapeHtml(item.httpStatusCode)}</td>
                    <td>${escapeHtml(item.durationMs)} ms</td>
                    <td class="mono">${escapeHtml(item.correlationId)}</td>
                </tr>
            `;
        });

        html += "</table>";
        return html;
    }

    async function loadRequestHistory() {
        const historyBox = document.getElementById("requestHistory");
        historyBox.innerHTML = "Loading request history...";

        try {
            const response = await fetch(
                `/ops/api/request-history?key=${encodeURIComponent(opsKey)}`
            );
            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    typeof data.detail === "string"
                        ? data.detail
                        : JSON.stringify(data.detail)
                );
            }

            historyBox.innerHTML = renderRequestHistory(data.items || []);
        } catch (error) {
            historyBox.innerHTML = `
                <p class="fail">HISTORY ERROR: ${escapeHtml(error.message)}</p>
            `;
        }
    }

    async function runPartnerMatrixRequest() {
        const partnerId = getSelectedPartner();
        const selectedFields = getSelectedAllowedFields();
        const extraTestField =
            document.getElementById("extraTestField").value.trim();
        const resultBox = document.getElementById("partnerMatrixResult");

        if (
            !verifiedDemoUrl ||
            !verifiedDemoKey ||
            verifiedPartnerId !== partnerId
        ) {
            resultBox.innerHTML = `
                <p class="fail">Complete URL and key verification first.</p>
            `;
            return;
        }

        const requestedFields = [...selectedFields];

        if (extraTestField) {
            requestedFields.push(extraTestField);
        }

        if (requestedFields.length === 0) {
            resultBox.innerHTML = `<p class="fail">Select at least one requested field.</p>`;
            return;
        }

        resultBox.innerHTML = "Running partner request via APIM...";

        try {
            const response = await fetch(
                `/ops/api/partner-matrix-request?key=${encodeURIComponent(opsKey)}`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        partnerId: partnerId,
                        requestedFields: requestedFields,
                        demoUrl: verifiedDemoUrl,
                        demoKey: verifiedDemoKey
                    })
                }
            );

            const data = await response.json();

            if (!response.ok && !data.result) {
                throw new Error(
                    typeof data.detail === "string"
                        ? data.detail
                        : JSON.stringify(data.detail)
                );
            }

            resultBox.innerHTML = renderPartnerMatrixResult(data);
            await loadRequestHistory();
        } catch (error) {
            resultBox.innerHTML = `<p class="fail">ERROR: ${escapeHtml(error.message)}</p>`;
        }
    }
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Ops routes
# ---------------------------------------------------------------------------

@router.get("/ops", response_class=HTMLResponse)
async def get_ops_console(key: str | None = Query(default=None)):
    require_ops_key(key)
    return HTMLResponse(OPS_CONSOLE_HTML)


@router.get("/ops/api/status")
async def get_ops_status(key: str | None = Query(default=None)):
    require_ops_key(key)

    return {
        "status": "PASS",
        "service": "dsr-api-gateway-ops-console",
        "runtime": "FastAPI",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "dataSourceMode": os.getenv("DATA_SOURCE_MODE", "mock"),
        "opsConsole": "enabled",
    }


@router.get("/ops/api/graph-signal")
async def get_graph_signal(key: str | None = Query(default=None)):
    require_ops_key(key)

    return await call_service_function(
        virtual_graph_service,
        ["build_graph_signal"],
    )


@router.get("/ops/api/data-protection")
async def get_data_protection(key: str | None = Query(default=None)):
    require_ops_key(key)

    return await call_service_function(
        virtual_graph_service,
        ["build_data_protection_report", "build_data_protection_check"],
    )


@router.get("/ops/api/apim-synthetic")
async def get_apim_synthetic(key: str | None = Query(default=None)):
    require_ops_key(key)

    return await call_service_function(
        apim_synthetic_check_service,
        ["build_apim_synthetic_check"],
    )


@router.get("/ops/api/full-check")
async def get_full_check(key: str | None = Query(default=None)):
    require_ops_key(key)

    try:
        return await call_service_function(
            ops_check_service,
            ["build_full_system_check", "build_ops_full_check", "build_full_check"],
        )
    except HTTPException:
        status = await get_ops_status(key)
        graph = await get_graph_signal(key)
        data_protection = await get_data_protection(key)
        apim_synthetic = await get_apim_synthetic(key)

        checks = [
            status,
            graph,
            data_protection,
            apim_synthetic,
        ]

        failed = [
            check
            for check in checks
            if check.get("status") not in ["PASS", "ALLOWED"]
            and check.get("overallStatus") != "PASS"
        ]

        return {
            "overallStatus": "PASS" if not failed else "FAIL",
            "summary": {
                "totalChecks": len(checks),
                "pass": len(checks) - len(failed),
                "fail": len(failed),
                "pending": 0,
            },
            "checks": {
                "status": status,
                "graphSignal": graph,
                "dataProtection": data_protection,
                "apimSynthetic": apim_synthetic,
            },
        }


@router.post("/ops/api/partner-access/verify-url")
async def post_partner_access_verify_url(
    payload: DemoUrlVerifyRequest,
    key: str | None = Query(default=None),
):
    require_ops_key(key)

    partner_id = normalize_partner_id(payload.partnerId)
    validate_partner_governance(partner_id)
    validate_demo_url(partner_id, payload.demoUrl)

    return JSONResponse(
        status_code=200,
        content={
            "status": "VERIFIED",
            "stage": "URL",
            "partnerId": partner_id,
            "demoUrl": payload.demoUrl.strip(),
            "mode": "SIMULATED_ONBOARDING_URL",
        },
    )


@router.post("/ops/api/partner-access/verify-key")
async def post_partner_access_verify_key(
    payload: DemoKeyVerifyRequest,
    key: str | None = Query(default=None),
):
    require_ops_key(key)

    partner_id = normalize_partner_id(payload.partnerId)
    governance = validate_partner_governance(partner_id)
    validate_demo_key(partner_id, payload.demoUrl, payload.demoKey)

    profile = get_partner_profile(partner_id)
    allowed_fields = profile.get("allowedFields", [])

    return JSONResponse(
        status_code=200,
        content={
            "status": "VERIFIED",
            "stage": "KEY",
            "partnerId": partner_id,
            "displayName": profile.get(
                "displayName",
                profile.get("partnerName", partner_id),
            ),
            "allowedFields": allowed_fields,
            "credentialMode": (
                "REAL_SERVER_CREDENTIAL"
                if partner_id in {"partner-a", "partner-b"}
                else "SIMULATED_PROFILE_SHARED_SERVER_CREDENTIAL"
            ),
            "gatewayMode": "REAL_APIM_AFTER_DEMO_VERIFICATION",
            "governance": build_governance_response(partner_id),
        },
    )




@router.get("/ops/api/partner-governance/{partner_id}")
async def get_partner_governance_profile(
    partner_id: str,
    key: str | None = Query(default=None),
):
    require_ops_key(key)

    return JSONResponse(
        status_code=200,
        content=build_governance_response(partner_id),
    )


@router.post("/ops/api/partner-governance")
async def update_partner_governance_profile(
    payload: PartnerGovernanceUpdateRequest,
    key: str | None = Query(default=None),
):
    require_ops_key(key)

    partner_id = normalize_partner_id(payload.partnerId)
    state = get_partner_governance(partner_id)

    try:
        datetime.strptime(payload.expiryDate, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="expiryDate must use YYYY-MM-DD format.",
        ) from exc

    state["isActive"] = payload.isActive
    state["expiryDate"] = payload.expiryDate
    state["quotaLimit"] = payload.quotaLimit

    if int(state.get("quotaUsed", 0)) > payload.quotaLimit:
        state["quotaUsed"] = payload.quotaLimit

    return JSONResponse(
        status_code=200,
        content=build_governance_response(partner_id),
    )


@router.get("/ops/api/request-history")
async def get_request_history(
    key: str | None = Query(default=None),
):
    require_ops_key(key)

    return JSONResponse(
        status_code=200,
        content={
            "status": "PASS",
            "count": len(REQUEST_HISTORY),
            "maxItems": REQUEST_HISTORY.maxlen,
            "storageMode": "IN_MEMORY_TEMPORARY",
            "items": get_request_history_snapshot(),
        },
    )


@router.post("/ops/api/partner-matrix-request")
async def post_partner_matrix_request(
    payload: PartnerMatrixOpsRequest,
    key: str | None = Query(default=None),
):
    require_ops_key(key)

    result = await call_partner_matrix_via_apim(payload)

    return JSONResponse(
        status_code=200,
        content=result,
    )
