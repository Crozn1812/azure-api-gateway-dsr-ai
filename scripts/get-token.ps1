param(
  [Parameter(Mandatory=$true)]
  [string]$PartnerClientSecret
)

if ([string]::IsNullOrWhiteSpace($TENANT_ID)) {
  Write-Error "TENANT_ID is missing. Run: . .\scripts\load-dev-env.ps1 first."
  exit 1
}

if ([string]::IsNullOrWhiteSpace($PARTNER_CLIENT_APP_ID)) {
  Write-Error "PARTNER_CLIENT_APP_ID is missing. Run: . .\scripts\load-dev-env.ps1 first."
  exit 1
}

if ([string]::IsNullOrWhiteSpace($DSR_API_APP_ID)) {
  Write-Error "DSR_API_APP_ID is missing. Run: . .\scripts\load-dev-env.ps1 first."
  exit 1
}

$TOKEN_RESPONSE = Invoke-RestMethod `
  -Method Post `
  -Uri "https://login.microsoftonline.com/$TENANT_ID/oauth2/v2.0/token" `
  -ContentType "application/x-www-form-urlencoded" `
  -Body @{
    client_id = $PARTNER_CLIENT_APP_ID
    client_secret = $PartnerClientSecret
    scope = "api://$DSR_API_APP_ID/.default"
    grant_type = "client_credentials"
  }

$global:ACCESS_TOKEN = $TOKEN_RESPONSE.access_token

if ([string]::IsNullOrWhiteSpace($global:ACCESS_TOKEN)) {
  Write-Error "Failed to acquire access token."
  exit 1
}

Write-Host "Access token acquired."
Write-Host "Token prefix: $($global:ACCESS_TOKEN.Substring(0,30))"