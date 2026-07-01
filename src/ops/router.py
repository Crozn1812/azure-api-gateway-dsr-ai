from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
import os

router = APIRouter(prefix="/ops", tags=["Operations Console"])


def _ops_enabled() -> bool:
    return os.getenv("ENABLE_OPS_CONSOLE", "true").lower() == "true"


def _check_ops_key(key: str | None) -> None:
    expected_key = os.getenv("OPS_CONSOLE_KEY", "demo-ops-key")

    if not _ops_enabled():
        raise HTTPException(status_code=404, detail="Ops console is disabled")

    if expected_key and key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid ops console key")


@router.get("", response_class=HTMLResponse)
def ops_console(key: str | None = Query(default=None)):
    _check_ops_key(key)

    html = f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8" />
        <title>DSR API Gateway Ops Console</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: #e5e7eb;
                margin: 0;
                padding: 32px;
            }}
            .container {{
                max-width: 1100px;
                margin: 0 auto;
            }}
            .card {{
                background: #111827;
                border: 1px solid #334155;
                border-radius: 14px;
                padding: 22px;
                margin-bottom: 18px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.25);
            }}
            h1 {{
                margin: 0 0 8px;
                font-size: 28px;
            }}
            h2 {{
                margin-top: 0;
                font-size: 20px;
                color: #bfdbfe;
            }}
            .muted {{
                color: #94a3b8;
            }}
            .status {{
                display: inline-block;
                padding: 6px 12px;
                border-radius: 999px;
                background: #064e3b;
                color: #bbf7d0;
                font-weight: bold;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 12px;
            }}
            th, td {{
                border-bottom: 1px solid #334155;
                padding: 12px;
                text-align: left;
            }}
            th {{
                color: #93c5fd;
            }}
            button {{
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 12px 18px;
                cursor: pointer;
                font-weight: bold;
            }}
            button:hover {{
                background: #1d4ed8;
            }}
            pre {{
                background: #020617;
                border: 1px solid #334155;
                padding: 16px;
                border-radius: 10px;
                overflow-x: auto;
            }}
            .pass {{
                color: #86efac;
                font-weight: bold;
            }}
            .warn {{
                color: #fde68a;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>DSR API Gateway Ops Console</h1>
                <p class="muted">
                    Operational demo environment for Azure API Gateway DSR API.
                    Không cần gõ lệnh để chứng minh hệ thống còn sống. Văn minh tối thiểu, cuối cùng cũng tới.
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
                        <td class="warn">PENDING</td>
                        <td>{os.getenv("DATA_SOURCE", "mock")}</td>
                    </tr>
                    <tr>
                        <td>Generated At</td>
                        <td class="pass">PASS</td>
                        <td>{datetime.now(timezone.utc).isoformat()}</td>
                    </tr>
                </table>
            </div>

            <div class="card">
                <h2>Operational Checks</h2>
                <p class="muted">
                    Các check thật sẽ được thêm ở bước sau: APIM, JWT, backend direct protection,
                    virtual Graph/SharePoint signal và data protection validation.
                </p>
                <button onclick="runStatusCheck()">Run Basic Status Check</button>
                <pre id="result">Chưa chạy check.</pre>
            </div>
        </div>

        <script>
            async function runStatusCheck() {{
                const params = new URLSearchParams(window.location.search);
                const key = params.get("key") || "";
                const res = await fetch(`/ops/api/status?key=${{encodeURIComponent(key)}}`);
                const data = await res.json();
                document.getElementById("result").textContent = JSON.stringify(data, null, 2);
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


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
                "message": "Ops console is reachable"
            },
            {
                "name": "Backend runtime",
                "status": "PASS",
                "message": "FastAPI backend is running"
            },
            {
                "name": "Full system check",
                "status": "PENDING",
                "message": "Will be implemented in Phase 7.4"
            },
            {
                "name": "Virtual Graph signal",
                "status": "PENDING",
                "message": "Will be implemented in Phase 7.2"
            },
            {
                "name": "Data protection validation",
                "status": "PENDING",
                "message": "Will be implemented in Phase 7.3"
            }
        ]
    }
