import json
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[1] / "data"

DSR_MATRIX_FILE = DATA_DIR / "dsr_matrix.json"
PARTNER_ACCESS_FILE = DATA_DIR / "partner_access_matrix.json"

SENSITIVE_FIELDS = {"internalNote", "personalData"}


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def evaluate_partner_request(partner_id: str, requested_fields: list[str]) -> dict:
    dsr_matrix = _load_json(DSR_MATRIX_FILE)
    partner_access = _load_json(PARTNER_ACCESS_FILE)

    normalized_partner_id = partner_id.strip().lower()
    requested_fields = [field.strip() for field in requested_fields if field.strip()]

    if normalized_partner_id not in partner_access:
        return {
            "status": "DENIED",
            "reason": f"Unknown partner: {partner_id}",
            "partnerId": normalized_partner_id,
            "requestedFields": requested_fields,
            "allowedData": [],
            "deniedFields": requested_fields,
        }

    partner_policy = partner_access[normalized_partner_id]
    allowed_fields = set(partner_policy.get("allowedFields", []))

    allowed_data = []
    denied_fields = []
    unknown_fields = []
    sensitive_violations = []

    for field in requested_fields:
        if field not in dsr_matrix:
            unknown_fields.append(field)
            denied_fields.append(field)
            continue

        if field in SENSITIVE_FIELDS:
            sensitive_violations.append(field)
            denied_fields.append(field)
            continue

        if field not in allowed_fields:
            denied_fields.append(field)
            continue

        allowed_data.append({
            "field": field,
            "value": dsr_matrix[field],
            "status": "ALLOWED"
        })

    result_status = "ALLOWED" if not denied_fields else "DENIED"

    return {
        "status": result_status,
        "partnerId": normalized_partner_id,
        "partnerName": partner_policy.get("displayName"),
        "requestedFields": requested_fields,
        "allowedFields": list(allowed_fields),
        "allowedData": allowed_data,
        "deniedFields": denied_fields,
        "unknownFields": unknown_fields,
        "sensitiveViolations": sensitive_violations,
        "policyMessage": (
            "Request is valid. All requested fields are allowed."
            if result_status == "ALLOWED"
            else "Request violates partner access policy."
        ),
    }