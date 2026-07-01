# API Contract - DSR Partner API

## 1. Tổng quan

POC này mô phỏng API Gateway trên Microsoft Azure cho kịch bản đối tác truy cập dữ liệu DSR đã được phê duyệt.

Luồng mô phỏng:

```text
Partner Client
→ API Gateway Mock Middleware
→ FastAPI Backend
→ SharePoint / Microsoft Graph Mock Service
→ JSON Response chuẩn