from datetime import datetime, timezone
from typing import Any


def get_virtual_graph_dsr_items() -> dict[str, Any]:
    """
    Simulate Microsoft Graph response for SharePoint list items.

    This is intentionally shaped like:
    GET /sites/{site-id}/lists/{list-id}/items?$expand=fields

    The raw source contains sensitive fields.
    The public API layer must never expose those fields to partners.
    """

    return {
        "@odata.context": (
            "https://graph.microsoft.com/v1.0/$metadata#"
            "sites('DSR')/lists('DSRRequests')/items"
        ),
        "source": {
            "provider": "Virtual Microsoft Graph",
            "site": "DSR",
            "list": "DSRRequests",
            "mode": "graph-shaped-simulation",
            "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
        "value": [
            {
                "id": "1",
                "fields": {
                    "requestId": "DSR-2026-0001",
                    "Title": "Yêu cầu tra cứu trạng thái xử lý",
                    "Status": "InProgress",
                    "CreatedDate": "2026-06-20T08:30:00Z",
                    "UpdatedDate": "2026-06-22T02:15:00Z",
                    "HptOwner": "DSR Team",
                    "SharedNote": "Đang xử lý theo SLA đã thống nhất",
                    "RequesterEmail": "requester01@example.com",
                    "InternalNote": "Internal investigation note. Not allowed for partner.",
                    "PersonalData": "Citizen ID / phone / private content placeholder",
                    "RawDescription": "Raw SharePoint description with internal processing details.",
                },
            },
            {
                "id": "2",
                "fields": {
                    "requestId": "DSR-2026-0002",
                    "Title": "Yêu cầu xác nhận dữ liệu đã chia sẻ",
                    "Status": "Completed",
                    "CreatedDate": "2026-06-18T03:10:00Z",
                    "UpdatedDate": "2026-06-21T09:45:00Z",
                    "HptOwner": "Compliance Team",
                    "SharedNote": "Đã hoàn tất theo phạm vi dữ liệu được phê duyệt",
                    "RequesterEmail": "requester02@example.com",
                    "InternalNote": "Legal review note. Internal only.",
                    "PersonalData": "Private data placeholder",
                    "RawDescription": "Raw SharePoint item content. Do not expose.",
                },
            },
            {
                "id": "3",
                "fields": {
                    "requestId": "DSR-2026-0003",
                    "Title": "Yêu cầu cập nhật trạng thái DSR",
                    "Status": "PendingReview",
                    "CreatedDate": "2026-06-22T11:00:00Z",
                    "UpdatedDate": "2026-06-23T01:20:00Z",
                    "HptOwner": "DSR Team",
                    "SharedNote": "Đang chờ rà soát phạm vi chia sẻ",
                    "RequesterEmail": "requester03@example.com",
                    "InternalNote": "Pending internal approval.",
                    "PersonalData": "Sensitive personal payload placeholder",
                    "RawDescription": "Internal workflow detail from SharePoint.",
                },
            },
        ],
        "@odata.nextLink": None,
    }


def map_graph_item_to_public_dsr(item: dict[str, Any]) -> dict[str, Any]:
    """
    Map raw Microsoft Graph SharePoint list item shape into public DSR API contract.

    This function is intentionally allowlist-based.
    Sensitive fields are ignored by design.
    """

    fields = item.get("fields", {})

    return {
        "requestId": fields.get("requestId"),
        "title": fields.get("Title"),
        "status": fields.get("Status"),
        "createdDate": fields.get("CreatedDate"),
        "updatedDate": fields.get("UpdatedDate"),
        "hptOwner": fields.get("HptOwner"),
        "sharedNote": fields.get("SharedNote"),
    }


def get_public_dsr_projection_from_virtual_graph() -> list[dict[str, Any]]:
    graph_response = get_virtual_graph_dsr_items()
    return [
        map_graph_item_to_public_dsr(item)
        for item in graph_response.get("value", [])
    ]


def validate_no_sensitive_fields(payload: Any) -> dict[str, Any]:
    """
    Validate that public payload does not expose sensitive source fields.
    """

    sensitive_markers = [
        "RequesterEmail",
        "requesterEmail",
        "InternalNote",
        "internalNote",
        "PersonalData",
        "personalData",
        "RawDescription",
        "rawDescription",
    ]

    payload_text = str(payload)

    leaked_fields = [
        marker
        for marker in sensitive_markers
        if marker in payload_text
    ]

    return {
        "status": "PASS" if not leaked_fields else "FAIL",
        "leakedFields": leaked_fields,
        "sensitiveFieldCount": len(leaked_fields),
    }


def build_graph_signal() -> dict[str, Any]:
    """
    Build an operational signal showing that the virtual Graph/SharePoint layer works.
    """

    graph_response = get_virtual_graph_dsr_items()
    public_projection = get_public_dsr_projection_from_virtual_graph()
    data_protection = validate_no_sensitive_fields(public_projection)

    raw_items = graph_response.get("value", [])

    return {
        "status": "PASS" if raw_items and data_protection["status"] == "PASS" else "FAIL",
        "signal": "Virtual Graph / SharePoint DSRRequests is reachable",
        "provider": "Virtual Microsoft Graph",
        "site": "DSR",
        "list": "DSRRequests",
        "rawItemCount": len(raw_items),
        "publicItemCount": len(public_projection),
        "rawShape": {
            "hasODataContext": "@odata.context" in graph_response,
            "hasValueArray": isinstance(graph_response.get("value"), list),
            "hasFieldsObject": bool(raw_items and "fields" in raw_items[0]),
            "hasNextLink": "@odata.nextLink" in graph_response,
        },
        "dataProtection": data_protection,
        "samplePublicItem": public_projection[0] if public_projection else None,
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
    }
PUBLIC_DSR_FIELDS = {
    "requestId",
    "title",
    "status",
    "createdDate",
    "updatedDate",
    "hptOwner",
    "sharedNote",
}

SENSITIVE_SOURCE_FIELDS = {
    "RequesterEmail",
    "requesterEmail",
    "InternalNote",
    "internalNote",
    "PersonalData",
    "personalData",
    "RawDescription",
    "rawDescription",
}


def build_data_protection_report() -> dict[str, Any]:
    """
    Build a dedicated data protection validation report.

    This proves that:
    - raw Graph-shaped source contains sensitive fields
    - public API projection does not expose sensitive fields
    - public output follows the approved allowlist contract
    """

    graph_response = get_virtual_graph_dsr_items()
    raw_items = graph_response.get("value", [])
    public_projection = get_public_dsr_projection_from_virtual_graph()

    raw_field_names = set()
    for item in raw_items:
        fields = item.get("fields", {})
        raw_field_names.update(fields.keys())

    raw_sensitive_fields_found = sorted(
        field for field in SENSITIVE_SOURCE_FIELDS if field in raw_field_names
    )

    public_payload_validation = validate_no_sensitive_fields(public_projection)

    public_items_field_report = []
    invalid_public_fields = set()
    missing_required_fields_by_item = []

    for item in public_projection:
        item_fields = set(item.keys())
        invalid_fields = item_fields - PUBLIC_DSR_FIELDS
        missing_fields = PUBLIC_DSR_FIELDS - item_fields

        invalid_public_fields.update(invalid_fields)

        public_items_field_report.append(
            {
                "requestId": item.get("requestId"),
                "fieldCount": len(item_fields),
                "fields": sorted(item_fields),
                "invalidFields": sorted(invalid_fields),
                "missingRequiredFields": sorted(missing_fields),
            }
        )

        if missing_fields:
            missing_required_fields_by_item.append(
                {
                    "requestId": item.get("requestId"),
                    "missingRequiredFields": sorted(missing_fields),
                }
            )

    checks = [
        {
            "name": "Raw source contains sensitive fields",
            "status": "PASS" if raw_sensitive_fields_found else "WARN",
            "message": (
                "Raw Graph-shaped source includes sensitive fields for validation"
                if raw_sensitive_fields_found
                else "No sensitive fields found in raw source; validation is less meaningful"
            ),
        },
        {
            "name": "Public projection blocks sensitive fields",
            "status": public_payload_validation["status"],
            "message": (
                "No sensitive fields leaked to public payload"
                if public_payload_validation["status"] == "PASS"
                else "Sensitive fields leaked to public payload"
            ),
        },
        {
            "name": "Public projection uses allowlist fields only",
            "status": "PASS" if not invalid_public_fields else "FAIL",
            "message": (
                "Public payload contains only approved fields"
                if not invalid_public_fields
                else "Public payload contains fields outside allowlist"
            ),
        },
        {
            "name": "Public projection has required fields",
            "status": "PASS" if not missing_required_fields_by_item else "FAIL",
            "message": (
                "All public items include required contract fields"
                if not missing_required_fields_by_item
                else "Some public items are missing required fields"
            ),
        },
        {
            "name": "Raw and public item count match",
            "status": "PASS" if len(raw_items) == len(public_projection) else "FAIL",
            "message": f"Raw items: {len(raw_items)}, public items: {len(public_projection)}",
        },
    ]

    failed_checks = [check for check in checks if check["status"] == "FAIL"]

    return {
        "status": "PASS" if not failed_checks else "FAIL",
        "purpose": "Validate that partner-facing API output does not leak sensitive SharePoint fields",
        "rawSource": {
            "provider": "Virtual Microsoft Graph",
            "site": "DSR",
            "list": "DSRRequests",
            "rawItemCount": len(raw_items),
            "rawSensitiveFieldsFound": raw_sensitive_fields_found,
        },
        "publicProjection": {
            "publicItemCount": len(public_projection),
            "allowedFields": sorted(PUBLIC_DSR_FIELDS),
            "invalidPublicFields": sorted(invalid_public_fields),
            "missingRequiredFieldsByItem": missing_required_fields_by_item,
            "leakedSensitiveFields": public_payload_validation["leakedFields"],
            "sensitiveFieldCount": public_payload_validation["sensitiveFieldCount"],
        },
        "checks": checks,
        "samplePublicItem": public_projection[0] if public_projection else None,
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
    }