import json
from pathlib import Path
from typing import List, Optional

from src.models.dsr import PublicDsrRequest


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "dsr_requests.json"


PUBLIC_FIELDS = {
    "requestId",
    "title",
    "status",
    "createdDate",
    "updatedDate",
    "hptOwner",
    "sharedNote",
}


def _load_raw_items() -> list[dict]:
    with open(DATA_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def _to_public_dto(raw_item: dict) -> PublicDsrRequest:
    public_data = {
        key: value
        for key, value in raw_item.items()
        if key in PUBLIC_FIELDS
    }
    return PublicDsrRequest(**public_data)


def get_dsr_requests(page_size: int = 50) -> List[PublicDsrRequest]:
    raw_items = _load_raw_items()
    return [_to_public_dto(item) for item in raw_items[:page_size]]


def get_dsr_request_by_id(request_id: str) -> Optional[PublicDsrRequest]:
    raw_items = _load_raw_items()

    for item in raw_items:
        if item.get("requestId") == request_id:
            return _to_public_dto(item)

    return None


def get_reference_data() -> dict:
    return {
        "statuses": ["Open", "InProgress", "Closed"],
        "requestTypes": ["Access", "Correction", "Deletion", "StatusInquiry"],
        "priorityLevels": ["Low", "Medium", "High"],
        "integrationNote": "Reference data is approved for partner integration."
    }