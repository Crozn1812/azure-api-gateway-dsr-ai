from typing import List, Optional

import requests

from src.core.config import get_settings
from src.models.dsr import PublicDsrRequest


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def _require_graph_config() -> None:
    settings = get_settings()

    missing = []

    if not settings.azure_tenant_id:
        missing.append("AZURE_TENANT_ID")
    if not settings.graph_client_id:
        missing.append("GRAPH_CLIENT_ID")
    if not settings.graph_client_secret:
        missing.append("GRAPH_CLIENT_SECRET")
    if not settings.sharepoint_site_id:
        missing.append("SHAREPOINT_SITE_ID")
    if not settings.sharepoint_list_id:
        missing.append("SHAREPOINT_LIST_ID")

    if missing:
        raise RuntimeError(
            "Missing Graph configuration: " + ", ".join(missing)
        )


def _get_graph_token() -> str:
    settings = get_settings()
    _require_graph_config()

    token_url = (
        f"https://login.microsoftonline.com/"
        f"{settings.azure_tenant_id}/oauth2/v2.0/token"
    )

    response = requests.post(
        token_url,
        data={
            "client_id": settings.graph_client_id,
            "client_secret": settings.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=15,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to acquire Graph token: {response.status_code} {response.text}"
        )

    return response.json()["access_token"]


def _graph_headers() -> dict:
    token = _get_graph_token()

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _pick(fields: dict, *names: str, default: str = "") -> str:
    for name in names:
        value = fields.get(name)
        if value is not None:
            return str(value)
    return default


def _map_graph_item_to_public_dsr(item: dict) -> PublicDsrRequest:
    fields = item.get("fields", {})

    request_id = _pick(
        fields,
        "requestId",
        "RequestId",
        "RequestID",
        "DSRRequestId",
        default=item.get("id", ""),
    )

    title = _pick(
        fields,
        "title",
        "Title",
        default="Untitled DSR request",
    )

    status = _pick(
        fields,
        "status",
        "Status",
        default="Unknown",
    )

    created_date = _pick(
        fields,
        "createdDate",
        "CreatedDate",
        default=item.get("createdDateTime", ""),
    )

    updated_date = _pick(
        fields,
        "updatedDate",
        "UpdatedDate",
        default=item.get("lastModifiedDateTime", ""),
    )

    hpt_owner = _pick(
        fields,
        "hptOwner",
        "HptOwner",
        "Owner",
        "owner",
        default="DSR Team",
    )

    shared_note = _pick(
        fields,
        "sharedNote",
        "SharedNote",
        default="",
    )

    return PublicDsrRequest(
        requestId=request_id,
        title=title,
        status=status,
        createdDate=created_date,
        updatedDate=updated_date,
        hptOwner=hpt_owner,
        sharedNote=shared_note,
    )


def get_dsr_requests_from_graph(page_size: int = 50) -> List[PublicDsrRequest]:
    settings = get_settings()
    headers = _graph_headers()

    url = (
        f"{GRAPH_BASE_URL}/sites/{settings.sharepoint_site_id}"
        f"/lists/{settings.sharepoint_list_id}/items"
    )

    response = requests.get(
        url,
        headers=headers,
        params={
            "$expand": "fields",
            "$top": page_size,
        },
        timeout=20,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Graph list items failed: {response.status_code} {response.text}"
        )

    items = response.json().get("value", [])
    return [_map_graph_item_to_public_dsr(item) for item in items]


def get_dsr_request_by_id_from_graph(request_id: str) -> Optional[PublicDsrRequest]:
    items = get_dsr_requests_from_graph(page_size=100)

    for item in items:
        if item.requestId == request_id:
            return item

    return None


def get_reference_data_from_graph() -> dict:
    return {
        "statuses": ["Open", "InProgress", "Closed"],
        "requestTypes": ["Access", "Correction", "Deletion", "StatusInquiry"],
        "priorityLevels": ["Low", "Medium", "High"],
        "integrationNote": "Reference data is approved for partner integration.",
        "dataSource": "microsoft-graph-sharepoint",
    }