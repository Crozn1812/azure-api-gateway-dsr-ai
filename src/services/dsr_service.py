from typing import List, Optional

from src.core.config import get_settings
from src.models.dsr import PublicDsrRequest
from src.services.sharepoint_mock_service import (
    get_dsr_requests as get_mock_dsr_requests,
    get_dsr_request_by_id as get_mock_dsr_request_by_id,
    get_reference_data as get_mock_reference_data,
)
from src.services.graph_sharepoint_service import (
    get_dsr_requests_from_graph,
    get_dsr_request_by_id_from_graph,
    get_reference_data_from_graph,
)


def get_dsr_requests(page_size: int = 50) -> List[PublicDsrRequest]:
    settings = get_settings()

    if settings.data_source == "graph":
        return get_dsr_requests_from_graph(page_size=page_size)

    return get_mock_dsr_requests(page_size=page_size)


def get_dsr_request_by_id(request_id: str) -> Optional[PublicDsrRequest]:
    settings = get_settings()

    if settings.data_source == "graph":
        return get_dsr_request_by_id_from_graph(request_id=request_id)

    return get_mock_dsr_request_by_id(request_id=request_id)


def get_reference_data() -> dict:
    settings = get_settings()

    if settings.data_source == "graph":
        return get_reference_data_from_graph()

    return get_mock_reference_data()