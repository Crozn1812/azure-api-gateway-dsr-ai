# Enterprise Runbook - Azure API Gateway DSR AI POC

## 1. Mục tiêu

Runbook này hướng dẫn vận hành mô hình Azure API Gateway DSR AI POC ở mức enterprise simulation.

Hệ thống gồm:

- Azure API Management
- APIM Product và Subscription key
- APIM Policy
- APIM Named Value secret
- Azure Container App backend
- Log Analytics
- Azure Monitor Alerts
- GitHub Actions CI/CD

## 2. Luồng request production-oriented

```text
Partner
→ Azure API Management
→ Product / Subscription Key
→ APIM Policy
→ Backend internal secret
→ Azure Container App
→ DSR data processing
→ JSON response
→ Logs / Metrics / Alerts