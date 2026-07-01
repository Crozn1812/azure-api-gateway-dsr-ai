# Infrastructure as Code - DSR API Gateway POC

## Mục tiêu

Thư mục này chứa Bicep template mô tả hạ tầng Azure cho mô hình API Gateway DSR.

## Thành phần hạ tầng

- Azure Container Registry
- Azure Container Apps Environment
- Azure Container App backend
- Azure API Management
- APIM Product cho Partner DSR APIs
- APIM Named Value cho backend internal secret
- Log Analytics Workspace

## Luồng hệ thống

```text
Partner
→ Azure API Management
→ APIM Product + Subscription Key
→ APIM Policy
→ Container App Backend
→ JSON Response
→ Log Analytics