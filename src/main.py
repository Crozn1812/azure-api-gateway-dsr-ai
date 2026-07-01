from fastapi import FastAPI, Request, HTTPException, Header 
from fastapi.responses import JSONResponse

from src.middleware.apim_mock import ApimMockMiddleware
from src.models.dsr import (
    DsrListResponse,
    DsrDetailResponse,
    ReferenceDataResponse,
    DsrAiRequest,
    DsrAiResponse,
    Paging,
)
from src.services.dsr_service import (
    get_dsr_requests,
    get_dsr_request_by_id,
    get_reference_data,
)
from src.services.ai_service import summarize_dsr_request


app = FastAPI(
    title="Azure API Gateway DSR AI POC",
    description=(
        "Local POC mô phỏng Azure API Management, Azure Function, "
        "Microsoft Graph/SharePoint và OpenAI processing."
    ),
    version="0.1.0",
)

app.add_middleware(ApimMockMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    correlation_id = getattr(request.state, "correlation_id", "unknown")

    code_map = {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "UPSTREAM_ERROR",
        503: "UPSTREAM_ERROR",
    }

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "correlationId": correlation_id,
            "error": {
                "code": code_map.get(exc.status_code, "INTERNAL_ERROR"),
                "message": str(exc.detail),
            },
        },
    )


@app.get("/health")
def health():
    return {
        "service": "azure-api-gateway-dsr-ai",
        "status": "running",
    }
@app.get("/")
def root():
    return {
        "message": "Azure API Gateway DSR AI POC is running",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/partner/dsr/requests", response_model=DsrListResponse)
def list_dsr_requests(request: Request, pageSize: int = 50):
    correlation_id = request.state.correlation_id

    if pageSize <= 0 or pageSize > 100:
        raise HTTPException(
            status_code=400,
            detail="pageSize must be between 1 and 100.",
        )

    items = get_dsr_requests(page_size=pageSize)

    return DsrListResponse(
        correlationId=correlation_id,
        data=items,
        paging=Paging(
            pageSize=pageSize,
            nextToken=None,
        ),
    )


@app.get("/partner/dsr/requests/{requestId}", response_model=DsrDetailResponse)
def get_dsr_request(requestId: str, request: Request):
    correlation_id = request.state.correlation_id
    item = get_dsr_request_by_id(requestId)

    if not item:
        raise HTTPException(
            status_code=404,
            detail="DSR request not found or not allowed for current partner scope.",
        )

    return DsrDetailResponse(
        correlationId=correlation_id,
        data=item,
    )


@app.get("/partner/dsr/reference-data", response_model=ReferenceDataResponse)
def reference_data(request: Request):
    correlation_id = request.state.correlation_id

    return ReferenceDataResponse(
        correlationId=correlation_id,
        data=get_reference_data(),
    )


@app.post("/ai/dsr/summarize", response_model=DsrAiResponse)
def summarize_dsr(
    request_body: DsrAiRequest,
    x_partner_id: str = Header(..., alias="x-partner-id"),
    x_api_key: str = Header(..., alias="x-api-key"),
):
    return summarize_dsr_request(request_body)