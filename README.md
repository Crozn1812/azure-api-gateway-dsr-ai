# Azure API Gateway DSR AI POC

POC cá nhân mô phỏng kiến trúc API Gateway trên Microsoft Azure.

## Luồng mô phỏng

Partner Client  
→ API Gateway Mock Middleware  
→ FastAPI Backend kiểu Azure Function  
→ SharePoint / Microsoft Graph Mock Service  
→ OpenAI AI Processing optional  
→ JSON response chuẩn

## Chạy local

### 1. Tạo môi trường ảo

```powershell
python -m venv .venv
.venv\Scripts\activate