import inspect
import os
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from src.services import apim_synthetic_check_service
from src.services import ops_check_service
from src.services import virtual_graph_service


router = APIRouter()


class PartnerMatrixOpsRequest(BaseModel):
    partnerId: str = Field(..., example="partner-a")
    requestedFields: List[str] = Field(..., example=["a", "b", "c"])


def require_ops_key(key: str | None) -> None:
    expected_key = os.getenv("OPS_CONSOLE_KEY", "demo-ops-key")

    if not expected_key:
        raise HTTPException(status_code=403, detail="Ops console key is not configured.")

    if key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid ops console key.")


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
            detail=f"Missing token environment variables: {', '.join(missing)}",
        )

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": f"api://{api_app_id}/.default",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(token_url, data=payload)

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to acquire Entra ID access token.",
                "statusCode": response.status_code,
                "response": response.text[:500],
            },
        )

    token_data = response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=500,
            detail="Token response does not contain access_token.",
        )

    return access_token


async def call_partner_matrix_via_apim(payload: PartnerMatrixOpsRequest) -> Dict[str, Any]:
    partner_id = payload.partnerId.strip().lower()
    credentials = get_partner_gateway_credentials(partner_id)

    apim_gateway = os.getenv("APIM_GATEWAY") or os.getenv("OPS_APIM_GATEWAY_URL")
    api_path = os.getenv("API_PATH") or os.getenv("OPS_API_PATH", "partner-api")

    if not apim_gateway:
        raise HTTPException(
            status_code=500,
            detail="Missing APIM gateway URL.",
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

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(endpoint, headers=headers, json=request_body)

    try:
        response_body = response.json()
    except Exception:
        response_body = {
            "rawResponse": response.text,
        }

    return {
        "apimRoute": {
            "gatewayUrl": apim_gateway,
            "apiPath": api_path,
            "operation": "POST /partner/dsr/matrix-request",
            "calledThroughApim": True,
            "apimLogged": True,
            "credentialMode": (
                "real-partner-credential"
                if partner_id in {"partner-a", "partner-b"}
                else "simulated-partner-using-partner-a-credential"
            ),
        },
        "httpStatusCode": response.status_code,
        "result": response_body,
    }


OPS_CONSOLE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
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
            min-height: 120px;
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
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <h1>DSR API Gateway Ops Console</h1>
        <p class="muted">Operational demo environment for Azure API Gateway DSR API.</p>
        <span class="status">OPS CONSOLE ONLINE</span>
    </div>

    <div class="card">
        <h2>Environment Status</h2>
        <table>
            <tr>
                <th>Item</th>
                <th>Status</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Ops Console</td>
                <td class="pass">PASS</td>
                <td>Enabled</td>
            </tr>
            <tr>
                <td>Backend Runtime</td>
                <td class="pass">PASS</td>
                <td>FastAPI</td>
            </tr>
            <tr>
                <td>Data Source Mode</td>
                <td class="warn">CHECK VIA API</td>
                <td>Use Basic Status Check</td>
            </tr>
            <tr>
                <td>Virtual Graph Signal</td>
                <td class="warn">CHECK VIA API</td>
                <td>Use Virtual Graph Signal Check</td>
            </tr>
            <tr>
                <td>Data Protection</td>
                <td class="warn">CHECK VIA API</td>
                <td>Use Data Protection Check</td>
            </tr>
            <tr>
                <td>APIM/JWT Synthetic</td>
                <td class="warn">CHECK VIA API</td>
                <td>Use APIM/JWT Synthetic Check</td>
            </tr>
            <tr>
                <td>Full System Check</td>
                <td class="warn">CHECK VIA API</td>
                <td>Use Run Full System Check</td>
            </tr>
        </table>
    </div>

    <div class="card">
        <h2>Operational Checks</h2>
        <p class="muted">
            Run operational checks for the Enterprise API Gateway POC.
        </p>

        <button class="button-green" onclick="runCheck('full-check')">Run Full System Check</button>
        <button class="button-purple" onclick="runCheck('apim-synthetic')">Run APIM/JWT Synthetic Check</button>
        <button onclick="runCheck('status')">Run Basic Status Check</button>
        <button onclick="runCheck('graph-signal')">Run Virtual Graph Signal</button>
        <button onclick="runCheck('data-protection')">Run Data Protection Check</button>

        <pre id="opsResult">Ops Console UI loaded. Run a check.</pre>
    </div>

    <div class="card">
        <h2>Partner Request Simulator via APIM</h2>
        <p class="muted">
            Submit partner field request through APIM. APIM validates gateway policy, then backend validates partner field-level policy.
        </p>

        <div class="grid">
            <div>
                <label for="partnerId">Partner ID</label>
                <select id="partnerId">
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
                <label for="requestedFields">Requested Fields</label>
                <input id="requestedFields" value="a,b,c" placeholder="Example: a,b,c or a,b,internalNote">
            </div>
        </div>

        <button class="button-green" onclick="runPartnerMatrixRequest()">Send Request via APIM</button>
        <button onclick="setExample('a,b,c')">Example Allowed</button>
        <button onclick="setExample('a,b,internalNote')">Example Denied</button>
        <button onclick="setExample('a,b,c,d,e,f,AB')">Example Mixed</button>

        <div id="partnerMatrixResult" class="result-box">
            Partner Matrix result will appear here.
        </div>
    </div>
</div>

<script>
    const params = new URLSearchParams(window.location.search);
    const opsKey = params.get("key") || "";

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

    function setExample(value) {
        document.getElementById("requestedFields").value = value;
    }

    async function runCheck(checkName) {
        const resultBox = document.getElementById("opsResult");
        resultBox.textContent = `Running /ops/api/${checkName} ...`;

        try {
            const response = await fetch(`/ops/api/${checkName}?key=${encodeURIComponent(opsKey)}`);
            const data = await response.json();
            resultBox.textContent = JSON.stringify(data, null, 2);
        } catch (error) {
            resultBox.textContent = `ERROR: ${error}`;
        }
    }

    function renderPartnerMatrixResult(data) {
        const wrapper = document.createElement("div");

        const result = data.result || {};
        const status = result.status || "UNKNOWN";
        const policyMessage = result.policyMessage || "";
        const route = data.apimRoute || {};

        const statusClass = status === "ALLOWED" ? "badge-pass" : "badge-fail";

        let html = `
            <h3>
                Policy Result:
                <span class="badge ${statusClass}">${escapeHtml(status)}</span>
            </h3>

            <p><b>Message:</b> ${escapeHtml(policyMessage)}</p>

            <table>
                <tr>
                    <th>Gateway Item</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Called Through APIM</td>
                    <td>${escapeHtml(route.calledThroughApim)}</td>
                </tr>
                <tr>
                    <td>APIM Logged</td>
                    <td>${escapeHtml(route.apimLogged)}</td>
                </tr>
                <tr>
                    <td>Operation</td>
                    <td>${escapeHtml(route.operation)}</td>
                </tr>
                <tr>
                    <td>HTTP Status Code</td>
                    <td>${escapeHtml(data.httpStatusCode)}</td>
                </tr>
            </table>
        `;

        if (result.requestJourney && result.requestJourney.length > 0) {
            html += `
                <h3>Request Journey</h3>
                <table>
                    <tr>
                        <th>Step</th>
                        <th>Description</th>
                    </tr>
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
                    <tr>
                        <th>Field</th>
                        <th>Value</th>
                        <th>Status</th>
                    </tr>
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

        wrapper.innerHTML = html;
        return wrapper.innerHTML;
    }

    async function runPartnerMatrixRequest() {
        const partnerId = document.getElementById("partnerId").value.trim();
        const requestedFieldsText = document.getElementById("requestedFields").value.trim();

        const requestedFields = requestedFieldsText
            .split(",")
            .map(item => item.trim())
            .filter(item => item.length > 0);

        const resultBox = document.getElementById("partnerMatrixResult");
        resultBox.innerHTML = "Running partner request via APIM...";

        try {
            const response = await fetch(
                `/ops/api/partner-matrix-request?key=${encodeURIComponent(opsKey)}`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        partnerId: partnerId,
                        requestedFields: requestedFields
                    })
                }
            );

            const data = await response.json();
            resultBox.innerHTML = renderPartnerMatrixResult(data);
        } catch (error) {
            resultBox.innerHTML = `<p class="fail">ERROR: ${escapeHtml(error)}</p>`;
        }
    }
</script>
</body>
</html>
"""


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
def get_partner_gateway_credentials(partner_id: str) -> dict:
    normalized = partner_id.strip().lower()

    partner_a = {
        "client_id": os.getenv("PARTNER_A_CLIENT_ID") or os.getenv("OPS_SYNTHETIC_CLIENT_ID"),
        "client_secret": os.getenv("PARTNER_A_CLIENT_SECRET") or os.getenv("OPS_SYNTHETIC_CLIENT_SECRET"),
        "apim_key": os.getenv("PARTNER_A_APIM_KEY") or os.getenv("OPS_APIM_SUBSCRIPTION_KEY"),
    }

    partner_b = {
        "client_id": os.getenv("PARTNER_B_CLIENT_ID"),
        "client_secret": os.getenv("PARTNER_B_CLIENT_SECRET"),
        "apim_key": os.getenv("PARTNER_B_APIM_KEY"),
    }

    mapping = {
        "partner-a": partner_a,
        "partner-b": partner_b,
    }

    if normalized in {
        "partner-c",
        "partner-d",
        "partner-e",
        "partner-f",
        "partner-g",
    }:
        credentials = partner_a
    else:
        credentials = mapping.get(normalized)

    if not credentials:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported partner: {normalized}",
        )

    missing = [
        name
        for name, value in credentials.items()
        if not value
    ]

    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing credential for {normalized}: {', '.join(missing)}",
        )

    return credentials
