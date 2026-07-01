import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import get_settings
from src.core.logging import logger

PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}

class ApimMockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        settings = get_settings()

        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        partner_id = request.headers.get("x-partner-id")
        api_key = request.headers.get("x-api-key")
        apim_internal_secret = request.headers.get("x-apim-internal-secret")

        request.state.correlation_id = correlation_id
        request.state.partner_id = partner_id

        is_public_path = (
            request.url.path in PUBLIC_PATHS
            or request.url.path.startswith("/docs")
            or request.url.path.startswith("/openapi")
        )

        if not is_public_path:
            if settings.require_apim_secret:
                if not settings.backend_internal_secret or apim_internal_secret != settings.backend_internal_secret:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "correlationId": correlation_id,
                            "error": {
                                "code": "FORBIDDEN",
                                "message": "Request must go through API Gateway.",
                            },
                        },
                    )

            if not partner_id:
                return JSONResponse(
                    status_code=401,
                    content={
                        "correlationId": correlation_id,
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Missing partner id.",
                        },
                    },
                )

            if not api_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "correlationId": correlation_id,
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Missing API key.",
                        },
                    },
                )

            if api_key != settings.partner_api_key:
                return JSONResponse(
                    status_code=403,
                    content={
                        "correlationId": correlation_id,
                        "error": {
                            "code": "FORBIDDEN",
                            "message": "Invalid API key or partner scope.",
                        },
                    },
                )

        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        logger.info(
            f"correlationId={correlation_id} "
            f"partnerId={partner_id or '-'} "
            f"method={request.method} "
            f"path={request.url.path} "
            f"statusCode={response.status_code} "
            f"durationMs={duration_ms}"
        )

        response.headers["x-correlation-id"] = correlation_id
        return response