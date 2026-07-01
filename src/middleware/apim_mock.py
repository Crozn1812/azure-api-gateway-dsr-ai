import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import get_settings
from src.core.logging import logger


PUBLIC_EXACT_PATHS = {
    "/",
    "/health",
    "/favicon.ico",
    "/openapi.json",
}

PUBLIC_PREFIXES = (
    "/docs",
    "/redoc",
    "/ops",
)


def is_public_path(path: str) -> bool:
    """
    Paths that should bypass API gateway mock protection.

    These routes are intentionally public because they are used for:
    - health checks
    - OpenAPI docs
    - local operational demo console
    """
    if path in PUBLIC_EXACT_PATHS:
        return True

    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in PUBLIC_PREFIXES
    )


def error_response(
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "correlationId": correlation_id,
            "error": {
                "code": code,
                "message": message,
            },
        },
    )


class ApimMockMiddleware(BaseHTTPMiddleware):
    """
    Middleware mô phỏng lớp bảo vệ giữa APIM và backend.

    Mục tiêu:
    - Local/dev vẫn test được bằng x-api-key.
    - Azure backend có thể bắt buộc request phải đi qua APIM bằng x-apim-internal-secret.
    - Public routes như /health, /docs, /ops không bị chặn.
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        settings = get_settings()
        path = request.url.path

        if is_public_path(path):
            return await call_next(request)

        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        partner_id = request.headers.get("x-partner-id")
        api_key = request.headers.get("x-api-key")
        apim_internal_secret = request.headers.get("x-apim-internal-secret")

        request.state.correlation_id = correlation_id
        request.state.partner_id = partner_id

        if settings.require_apim_secret:
            if (
                not apim_internal_secret
                or apim_internal_secret != settings.backend_internal_secret
            ):
                return error_response(
                    status_code=403,
                    code="FORBIDDEN",
                    message="Request must go through API Gateway.",
                    correlation_id=correlation_id,
                )

        if not partner_id:
            return error_response(
                status_code=401,
                code="UNAUTHORIZED",
                message="Missing partner id.",
                correlation_id=correlation_id,
            )

        if api_key != settings.partner_api_key:
            return error_response(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid API key.",
                correlation_id=correlation_id,
            )

        response = await call_next(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)

        logger.info(
            "api_request_completed",
            extra={
                "correlation_id": correlation_id,
                "partner_id": partner_id,
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        response.headers["x-correlation-id"] = correlation_id
        response.headers["x-api-gateway"] = "apim-mock"

        return response