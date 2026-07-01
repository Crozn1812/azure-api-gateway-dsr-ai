from datetime import datetime, timezone
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.services.apim_synthetic_check_service import build_apim_synthetic_check
from src.services.ops_check_service import build_full_system_check
from src.services.virtual_graph_service import (
    build_data_protection_report,
    build_graph_signal,
)


router = APIRouter(prefix="/ops", tags=["Operations Console"])


def _ops_enabled() -> bool:
    return os.getenv("ENABLE_OPS_CONSOLE", "true").lower() == "true"


def _check_ops_key(key: str | None) -> None:
    expected_key = os.getenv("OPS_CONSOLE_KEY", "demo-ops-key")

    if not _ops_enabled():
        raise HTTPException(status_code=404, detail="Ops console is disabled")

    if expected_key and key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid ops console key")


OPS_CONSOLE_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8" />
    <title>DSR API Gateway Ops Console</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: #e5e7eb;
            margin: 0;
            padding: 32px;
        }

        .container {
            max-width: 1100px;
            margin: 0 auto;
        }

        .card {
            background: #111827;
            border: 1px solid #334155;
            border-radius: 14px;
            padding: 22px;
            margin-bottom: 18px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.25);
        }

        h1 {
            margin: 0 0 8px;
            font-size: 28px;
        }

        h2 {
            margin-top: 0;
            font-size: 20px;
            color: #bfdbfe;
        }

        .muted {
            color: #94a3b8;
        }

        .status {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 999px;
            background: #064e3b;
            color: #bbf7d0;
            font-weight: bold;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }

        th, td {
            border-bottom: 1px solid #334155;
            padding: 12px;
            text-align: left;
        }

        th {
            color: #93c5fd;
        }

        button {
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 10px;
            padding: 12px 18px;
            cursor: pointer;
            font-weight: bold;
            margin-right: 8px;
            margin-bottom: 8px;
        }

        button:hover {
            background: #1d4ed8;
        }

        pre {
            background: #020617;
            border: 1px solid #334155;
            padding: 16px;
            border-radius: 10px;
            overflow-x: auto;
            min-height: 330px;
            white-space: pre-wrap;
        }

        .pass {
            color: #86efac;
            font-weight: bold;
        }

        .warn {
            color: #fde68a;
            font-weight: bold;
        }

        .fail {
            color: #fca5a5;
            font-weight: bold;
        }

        .button-primary {
            background: #16a34a;
        }

        .button-primary:hover {
            background: #15803d;
        }

        .button-apim {
            background: #7c3aed;
        }

        .button-apim:hover {
            background: #6d28d9;
        }
    </style>
</head>

<body>
    <div class="container">
        <div class="card">
            <h1>DSR API Gateway Ops Console</h1>
            <p class="muted">
                Operational demo environment for Azure API Gateway DSR API.
                Không cần gõ lệnh để chứng minh hệ thống còn sống.
            </p>
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
                Đây là bảng kiểm tra vận hành của mô hình Enterprise API Gateway POC.
                Full System Check sẽ gom basic status, virtual Graph signal, data protection
                và APIM/JWT synthetic live check.
            </p>

            <button id="btn-full-check" class="button-primary">Run Full System Check</button>
            <button id="btn-apim-synthetic" class="button-apim">Run APIM/JWT Synthetic Check</button>
            <button id="btn-status">Run Basic Status Check</button>
            <button id="btn-graph">Run Virtual Graph Signal</button>
            <button id="btn-data-protection">Run Data Protection Check</button>

            <pre id="result">Chưa chạy check.</pre>
        </div>
    </div>

    <script>
        function getOpsKey() {
            const params = new URLSearchParams(window.location.search);
            return params.get("key") || "";
        }

        function showResult(value) {
            const result = document.getElementById("result");
            result.textContent = typeof value === "string"
                ? value
                : JSON.stringify(value, null, 2);
        }

        async function callOpsApi(endpoint) {
            const key = getOpsKey();
            const url = `${endpoint}?key=${encodeURIComponent(key)}`;

            showResult(`Running check: ${url}\\nPlease wait...`);

            const controller = new AbortController();
            const timeoutId = setTimeout(function () {
                controller.abort();
            }, 60000);

            try {
                const startedAt = performance.now();

                const response = await fetch(url, {
                    method: "GET",
                    headers: {
                        "Accept": "application/json"
                    },
                    signal: controller.signal
                });

                clearTimeout(timeoutId);

                const durationMs = Math.round(performance.now() - startedAt);
                const text = await response.text();

                let data;
                try {
                    data = JSON.parse(text);
                } catch {
                    data = {
                        status: "FAIL",
                        message: "Response is not valid JSON",
                        rawResponse: text
                    };
                }

                showResult({
                    uiStatus: "COMPLETED",
                    httpStatus: response.status,
                    ok: response.ok,
                    endpoint: endpoint,
                    durationMs: durationMs,
                    response: data
                });
            } catch (error) {
                clearTimeout(timeoutId);

                showResult({
                    uiStatus: "FAILED",
                    endpoint: endpoint,
                    message: "Browser could not complete the request",
                    error: String(error)
                });
            }
        }

        document.addEventListener("DOMContentLoaded", function () {
            const fullCheckButton = document.getElementById("btn-full-check");
            const apimSyntheticButton = document.getElementById("btn-apim-synthetic");
            const statusButton = document.getElementById("btn-status");
            const graphButton = document.getElementById("btn-graph");
            const dataProtectionButton = document.getElementById("btn-data-protection");

            fullCheckButton.addEventListener("click", function () {
                callOpsApi("/ops/api/full-check");
            });

            apimSyntheticButton.addEventListener("click", function () {
                callOpsApi("/ops/api/apim-synthetic");
            });

            statusButton.addEventListener("click", function () {
                callOpsApi("/ops/api/status");
            });

            graphButton.addEventListener("click", function () {
                callOpsApi("/ops/api/graph-signal");
            });

            dataProtectionButton.addEventListener("click", function () {
                callOpsApi("/ops/api/data-protection");
            });

            showResult("Ops Console UI loaded. Bấm một nút để chạy check.");
        });
    </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
def ops_console(key: str | None = Query(default=None)):
    _check_ops_key(key)
    return HTMLResponse(content=OPS_CONSOLE_HTML)


@router.get("/api/status")
def ops_status(key: str | None = Query(default=None)):
    _check_ops_key(key)

    return {
        "status": "PASS",
        "service": "DSR API Gateway Ops Console",
        "opsConsoleEnabled": _ops_enabled(),
        "dataSource": os.getenv("DATA_SOURCE", "mock"),
        "environment": os.getenv("ENVIRONMENT", "local"),
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
        "checks": [
            {
                "name": "Ops console route",
                "status": "PASS",
                "message": "Ops console is reachable",
            },
            {
                "name": "Backend runtime",
                "status": "PASS",
                "message": "FastAPI backend is running",
            },
            {
                "name": "Virtual Graph signal",
                "status": "READY",
                "message": "Use /ops/api/graph-signal to run the check",
            },
            {
                "name": "Data protection validation",
                "status": "READY",
                "message": "Use /ops/api/data-protection to run the check",
            },
            {
                "name": "APIM/JWT synthetic check",
                "status": "CHECK_VIA_API",
                "message": "Use /ops/api/apim-synthetic to run the live synthetic check",
            },
            {
                "name": "Full system check",
                "status": "CHECK_VIA_API",
                "message": "Use /ops/api/full-check to run the combined operational check",
            },
        ],
    }


@router.get("/api/graph-signal")
def graph_signal(key: str | None = Query(default=None)):
    _check_ops_key(key)
    return build_graph_signal()


@router.get("/api/data-protection")
def data_protection_check(key: str | None = Query(default=None)):
    _check_ops_key(key)
    return build_data_protection_report()


@router.get("/api/apim-synthetic")
def apim_synthetic_check(key: str | None = Query(default=None)):
    _check_ops_key(key)
    return build_apim_synthetic_check()


@router.get("/api/full-check")
def full_system_check(key: str | None = Query(default=None)):
    _check_ops_key(key)
    return build_full_system_check()