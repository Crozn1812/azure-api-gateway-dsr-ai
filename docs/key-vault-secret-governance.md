# Key Vault & Secret Governance - Azure API Gateway DSR AI

## 1. Mục tiêu

Phase này bổ sung Azure Key Vault vào mô hình để quản lý secret theo hướng production enterprise.

## 2. Trạng thái hiện tại

Đã có:

- Azure Key Vault
- Secret `backend-internal-secret` trong Key Vault
- Backend internal secret đang được dùng để chặn request không đi qua APIM
- APIM Named Value secret `backend-internal-secret`
- Container App secret `backend-internal-secret`

## 3. Giới hạn hiện tại

APIM hiện tại đang dùng Consumption tier.

Khi bật System Assigned Managed Identity cho APIM bằng lệnh:

```powershell
az apim update `
  --name $APIM_NAME `
  --resource-group $RG `
  --set identity.type=SystemAssigned