$RG="rg-dsr-api-phase3"
$LOCATION="southeastasia"

$APIM_NAME="apim-dsr-api-71726"
$API_ID="dsr-api"
$APP_NAME="ca-dsr-api-phase3"

$TENANT_ID = az account show --query tenantId -o tsv
$AZ_SUB_ID = az account show --query id -o tsv

$APIM_GATEWAY = az apim show `
  --name $APIM_NAME `
  --resource-group $RG `
  --query gatewayUrl `
  -o tsv

$API_PATH = az apim api show `
  --resource-group $RG `
  --service-name $APIM_NAME `
  --api-id $API_ID `
  --query path `
  -o tsv

$APP_URL = az containerapp show `
  --name $APP_NAME `
  --resource-group $RG `
  --query "properties.configuration.ingress.fqdn" `
  -o tsv

$DSR_API_APP_ID = az ad app list `
  --display-name "dsr-api-resource" `
  --query "[0].appId" `
  -o tsv

$PARTNER_CLIENT_APP_ID = az ad app list `
  --display-name "partner-a-client" `
  --query "[0].appId" `
  -o tsv

Write-Host "Loaded Azure DSR API variables."
Write-Host "APIM_GATEWAY=$APIM_GATEWAY"
Write-Host "API_PATH=$API_PATH"
Write-Host "APP_URL=$APP_URL"
Write-Host "DSR_API_APP_ID=$DSR_API_APP_ID"
Write-Host "PARTNER_CLIENT_APP_ID=$PARTNER_CLIENT_APP_ID"