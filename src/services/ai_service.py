import json
from src.core.config import get_settings
from src.models.dsr import DsrAiRequest, DsrAiResponse


def _fallback_summary(request: DsrAiRequest) -> DsrAiResponse:
    risk_level = "Medium" if request.status in ["Open", "InProgress"] else "Low"

    return DsrAiResponse(
        requestId=request.requestId,
        summary=f"Yêu cầu {request.requestId} đang ở trạng thái {request.status}.",
        riskLevel=risk_level,
        suggestedAction="Theo dõi trạng thái xử lý và cập nhật cho đối tác khi có thay đổi.",
        partnerMessage="Yêu cầu đã được ghi nhận và đang được xử lý theo phạm vi chia sẻ đã thống nhất."
    )


def summarize_dsr_request(request: DsrAiRequest) -> DsrAiResponse:
    settings = get_settings()

    if not settings.openai_api_key:
        return _fallback_summary(request)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)

        prompt = f"""
Bạn là AI service trong hệ thống API Gateway doanh nghiệp.

Nhiệm vụ:
- Tóm tắt yêu cầu DSR.
- Đánh giá riskLevel: Low, Medium hoặc High.
- Đề xuất hành động tiếp theo.
- Viết partnerMessage ngắn gọn, lịch sự, không lộ dữ liệu nội bộ.
- Chỉ trả JSON hợp lệ.
- Không thêm dữ liệu không có trong input.

Input:
requestId: {request.requestId}
title: {request.title}
status: {request.status}
createdDate: {request.createdDate}
updatedDate: {request.updatedDate}
hptOwner: {request.hptOwner}
sharedNote: {request.sharedNote}

Output JSON schema:
{{
  "requestId": "{request.requestId}",
  "summary": "...",
  "riskLevel": "Low | Medium | High",
  "suggestedAction": "...",
  "partnerMessage": "..."
}}
"""

        response = client.responses.create(
            model=settings.openai_model,
            input=prompt
        )

        data = json.loads(response.output_text)
        return DsrAiResponse(**data)

    except Exception:
        return _fallback_summary(request)