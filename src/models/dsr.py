from typing import Optional, List
from pydantic import BaseModel


class PublicDsrRequest(BaseModel):
    requestId: str
    title: str
    status: str
    createdDate: str
    updatedDate: str
    hptOwner: str
    sharedNote: Optional[str] = None


class Paging(BaseModel):
    pageSize: int = 50
    nextToken: Optional[str] = None


class DsrListResponse(BaseModel):
    correlationId: str
    data: List[PublicDsrRequest]
    paging: Paging


class DsrDetailResponse(BaseModel):
    correlationId: str
    data: PublicDsrRequest


class ReferenceDataResponse(BaseModel):
    correlationId: str
    data: dict


class DsrAiRequest(BaseModel):
    requestId: str
    title: str
    status: str
    createdDate: Optional[str] = None
    updatedDate: Optional[str] = None
    hptOwner: Optional[str] = None
    sharedNote: Optional[str] = None


class DsrAiResponse(BaseModel):
    requestId: str
    summary: str
    riskLevel: str
    suggestedAction: str
    partnerMessage: str