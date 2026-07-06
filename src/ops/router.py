import inspect
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from src.services import apim_synthetic_check_service
from src.services import ops_check_service
from src.services import virtual_graph_service


router = APIRouter()


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


async def call_partner_matrix_via_apim(
    payload: PartnerMatrixOpsRequest,
) -> Dict[str, Any]:
    partner_id = normalize_partner_id(payload.partnerId)

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

    return {
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

        <label for="requestedFields">Requested Fields</label>
        <input
            id="requestedFields"
            value=""
            placeholder="Example: a,b,c or a,b,internalNote"
        >

        <button class="button-green" onclick="runPartnerMatrixRequest()">Send Request via APIM</button>
        <button onclick="fillAllowedFields()">Use All Allowed Fields</button>
        <button onclick="setSensitiveExample()">Add internalNote Test</button>

        <div id="partnerMatrixResult" class="result-box">
            Partner Matrix result will appear here.
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
        document.getElementById("requestedFields").value = "";
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

    function fillAllowedFields() {
        document.getElementById("requestedFields").value = allowedFields.join(",");
    }

    function setSensitiveExample() {
        const base = allowedFields.slice(0, 2);
        base.push("internalNote");
        document.getElementById("requestedFields").value = base.join(",");
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
            `;

            const chips = allowedFields
                .map(field => `<span class="field-chip">${escapeHtml(field)}</span>`)
                .join("");

            document.getElementById("partnerProfile").innerHTML = `
                <h3>Partner Access Profile</h3>
                <p><b>Partner:</b> ${escapeHtml(data.displayName || data.partnerId)}</p>
                <p><b>Status:</b> <span class="badge badge-pass">ACTIVE</span></p>
                <p><b>Allowed Fields:</b></p>
                <div>${chips}</div>
            `;

            document.getElementById("requestedFields").value = allowedFields.join(",");
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

    async function runPartnerMatrixRequest() {
        const partnerId = getSelectedPartner();
        const requestedFieldsText =
            document.getElementById("requestedFields").value.trim();
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

        const requestedFields = requestedFieldsText
            .split(",")
            .map(item => item.trim())
            .filter(item => item.length > 0);

        if (requestedFields.length === 0) {
            resultBox.innerHTML = `<p class="fail">Enter at least one requested field.</p>`;
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
