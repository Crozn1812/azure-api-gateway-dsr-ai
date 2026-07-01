param(
  [Parameter(Mandatory=$true)]
  [string]$ApimSubscriptionKey
)

$ErrorActionPreference = "Stop"

function Assert-Contains {
  param(
    [string]$Text,
    [string]$Expected,
    [string]$TestName
  )

  if ($Text -like "*$Expected*") {
    Write-Host "[PASS] $TestName"
  } else {
    Write-Host "[FAIL] $TestName"
    Write-Host "Expected to contain: $Expected"
    Write-Host "Actual:"
    Write-Host $Text
    exit 1
  }
}

if ([string]::IsNullOrWhiteSpace($APIM_GATEWAY)) {
  Write-Error "APIM_GATEWAY missing. Run: . .\scripts\load-dev-env.ps1"
  exit 1
}

if ([string]::IsNullOrWhiteSpace($API_PATH)) {
  Write-Error "API_PATH missing. Run: . .\scripts\load-dev-env.ps1"
  exit 1
}

if ([string]::IsNullOrWhiteSpace($APP_URL)) {
  Write-Error "APP_URL missing. Run: . .\scripts\load-dev-env.ps1"
  exit 1
}

Write-Host "Running smoke tests..."

Write-Host "Test 1: APIM without token should return 401"
$missingTokenResponse = curl.exe `
  -H "x-partner-id: partner-a" `
  -H "Ocp-Apim-Subscription-Key: $ApimSubscriptionKey" `
  "$APIM_GATEWAY/$API_PATH/partner/dsr/requests"

Assert-Contains `
  -Text ($missingTokenResponse | Out-String) `
  -Expected "Unauthorized. Access token is missing or invalid." `
  -TestName "Missing token returns 401"

if ([string]::IsNullOrWhiteSpace($ACCESS_TOKEN)) {
  Write-Error "ACCESS_TOKEN missing. Run: . .\scripts\get-token.ps1 -PartnerClientSecret '<secret>'"
  exit 1
}

Write-Host "Test 2: APIM with valid token should return 200 data"
$validTokenResponse = curl.exe `
  -H "x-partner-id: partner-a" `
  -H "Ocp-Apim-Subscription-Key: $ApimSubscriptionKey" `
  -H "Authorization: Bearer $ACCESS_TOKEN" `
  "$APIM_GATEWAY/$API_PATH/partner/dsr/requests"

Assert-Contains `
  -Text ($validTokenResponse | Out-String) `
  -Expected "correlationId" `
  -TestName "Valid token returns API response"

Assert-Contains `
  -Text ($validTokenResponse | Out-String) `
  -Expected "DSR-2026-0001" `
  -TestName "Valid token returns DSR data"

Write-Host "Test 3: Backend direct call should return 403"
$backendDirectResponse = curl.exe `
  -H "x-partner-id: partner-a" `
  -H "x-api-key: demo-partner-key" `
  "https://$APP_URL/partner/dsr/requests"

Assert-Contains `
  -Text ($backendDirectResponse | Out-String) `
  -Expected "Request must go through API Gateway." `
  -TestName "Backend direct call blocked"

Write-Host "All smoke tests passed."