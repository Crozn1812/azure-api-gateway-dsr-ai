param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$OpsKey = "demo-ops-key"
)

$ErrorActionPreference = "Stop"

$results = @()

function Add-Result {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Expected,
        [string]$Actual
    )

    $results += [pscustomobject]@{
        Test     = $Name
        Result   = if ($Passed) { "PASS" } else { "FAIL" }
        Expected = $Expected
        Actual   = $Actual
    }

    Set-Variable -Name results -Value $results -Scope Script
}

function Invoke-JsonRequest {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Path,
        [hashtable]$Body
    )

    $uri = "$BaseUrl$Path"

    try {
        if ($Method -eq "GET") {
            $response = Invoke-WebRequest `
                -Method Get `
                -Uri $uri `
                -UseBasicParsing
        }
        else {
            $json = $Body | ConvertTo-Json -Depth 10
            $response = Invoke-WebRequest `
                -Method Post `
                -Uri $uri `
                -ContentType "application/json" `
                -Body $json `
                -UseBasicParsing
        }

        $content = $null
        if ($response.Content) {
            try {
                $content = $response.Content | ConvertFrom-Json
            }
            catch {
                $content = $response.Content
            }
        }

        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Body       = $content
        }
    }
    catch {
        $statusCode = 0
        $body = $null

        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }

        if ($_.ErrorDetails.Message) {
            try {
                $body = $_.ErrorDetails.Message | ConvertFrom-Json
            }
            catch {
                $body = $_.ErrorDetails.Message
            }
        }

        return [pscustomobject]@{
            StatusCode = $statusCode
            Body       = $body
        }
    }
}

function Set-Governance {
    param(
        [string]$PartnerId,
        [bool]$IsActive = $true,
        [string]$ExpiryDate = "2026-12-31",
        [int]$QuotaLimit = 100
    )

    Invoke-JsonRequest `
        -Method POST `
        -Path "/ops/api/partner-governance?key=$([uri]::EscapeDataString($OpsKey))" `
        -Body @{
            partnerId  = $PartnerId
            isActive   = $IsActive
            expiryDate = $ExpiryDate
            quotaLimit = $QuotaLimit
        }
}

function Verify-Url {
    param(
        [string]$PartnerId,
        [string]$DemoUrl
    )

    Invoke-JsonRequest `
        -Method POST `
        -Path "/ops/api/partner-access/verify-url?key=$([uri]::EscapeDataString($OpsKey))" `
        -Body @{
            partnerId = $PartnerId
            demoUrl   = $DemoUrl
        }
}

function Verify-Key {
    param(
        [string]$PartnerId,
        [string]$DemoUrl,
        [string]$DemoKey
    )

    Invoke-JsonRequest `
        -Method POST `
        -Path "/ops/api/partner-access/verify-key?key=$([uri]::EscapeDataString($OpsKey))" `
        -Body @{
            partnerId = $PartnerId
            demoUrl   = $DemoUrl
            demoKey   = $DemoKey
        }
}

function Request-PartnerData {
    param(
        [string]$PartnerId,
        [string]$DemoUrl,
        [string]$DemoKey,
        [string[]]$RequestedFields
    )

    Invoke-JsonRequest `
        -Method POST `
        -Path "/ops/api/partner-matrix-request?key=$([uri]::EscapeDataString($OpsKey))" `
        -Body @{
            partnerId       = $PartnerId
            demoUrl         = $DemoUrl
            demoKey         = $DemoKey
            requestedFields = $RequestedFields
        }
}

$partners = @{
    "partner-a" = @{
        Url    = "https://demo.partner-a.local/api"
        Key    = "demo-key-a"
        Fields = @("a", "b", "c", "1", "2", "AB")
    }
    "partner-b" = @{
        Url    = "https://demo.partner-b.local/api"
        Key    = "demo-key-b"
        Fields = @("d", "e", "f", "3", "4", "AF")
    }
    "partner-c" = @{
        Url    = "https://demo.partner-c.local/api"
        Key    = "demo-key-c"
        Fields = @("a", "c", "e", "5", "6", "AF")
    }
    "partner-d" = @{
        Url    = "https://demo.partner-d.local/api"
        Key    = "demo-key-d"
        Fields = @("b", "d", "f", "1", "3", "5", "AE")
    }
    "partner-e" = @{
        Url    = "https://demo.partner-e.local/api"
        Key    = "demo-key-e"
        Fields = @("a", "b", "c", "d", "e", "f", "1", "2", "3", "4", "5", "6", "AB")
    }
    "partner-f" = @{
        Url    = "https://demo.partner-f.local/api"
        Key    = "demo-key-f"
        Fields = @("a", "b", "c", "d", "e", "f", "1", "2", "3", "4", "5", "6", "AC")
    }
    "partner-g" = @{
        Url    = "https://demo.partner-g.local/api"
        Key    = "demo-key-g"
        Fields = @("a", "b", "c", "d", "e", "f", "1", "2", "3", "4", "5", "6", "AD")
    }
}

Write-Host ""
Write-Host "Phase 9.5 E2E Test - DSR Partner Simulator" -ForegroundColor Cyan
Write-Host "Target: $BaseUrl" -ForegroundColor DarkGray
Write-Host ""

# Reset all partner governance before testing.
foreach ($partnerId in $partners.Keys) {
    $null = Set-Governance `
        -PartnerId $partnerId `
        -IsActive $true `
        -ExpiryDate "2026-12-31" `
        -QuotaLimit 100
}

# 1. Wrong URL -> 401
$wrongUrl = Verify-Url `
    -PartnerId "partner-a" `
    -DemoUrl "https://wrong.local/api"

Add-Result `
    -Name "Wrong URL is rejected" `
    -Passed ($wrongUrl.StatusCode -eq 401) `
    -Expected "401" `
    -Actual "$($wrongUrl.StatusCode)"

# 2. Wrong key -> 401
$wrongKey = Verify-Key `
    -PartnerId "partner-a" `
    -DemoUrl $partners["partner-a"].Url `
    -DemoKey "wrong-key"

Add-Result `
    -Name "Wrong demo key is rejected" `
    -Passed ($wrongKey.StatusCode -eq 401) `
    -Expected "401" `
    -Actual "$($wrongKey.StatusCode)"

# 3. All partner URL/key profiles verify
foreach ($partnerId in ($partners.Keys | Sort-Object)) {
    $partner = $partners[$partnerId]

    $urlResult = Verify-Url `
        -PartnerId $partnerId `
        -DemoUrl $partner.Url

    Add-Result `
        -Name "$partnerId URL verification" `
        -Passed ($urlResult.StatusCode -eq 200 -and $urlResult.Body.status -eq "VERIFIED") `
        -Expected "200 VERIFIED" `
        -Actual "$($urlResult.StatusCode) $($urlResult.Body.status)"

    $keyResult = Verify-Key `
        -PartnerId $partnerId `
        -DemoUrl $partner.Url `
        -DemoKey $partner.Key

    $actualFields = @($keyResult.Body.allowedFields)
    $expectedFields = @($partner.Fields)

    $fieldMatch = (
        (Compare-Object `
            -ReferenceObject ($expectedFields | Sort-Object) `
            -DifferenceObject ($actualFields | Sort-Object)
        ).Count -eq 0
    )

    Add-Result `
        -Name "$partnerId key and scope verification" `
        -Passed (
            $keyResult.StatusCode -eq 200 `
            -and $keyResult.Body.status -eq "VERIFIED" `
            -and $fieldMatch
        ) `
        -Expected "200 VERIFIED + correct scope" `
        -Actual "$($keyResult.StatusCode) $($keyResult.Body.status) fields=$($actualFields -join ',')"
}

# 4. Allowed request for every partner
foreach ($partnerId in ($partners.Keys | Sort-Object)) {
    $partner = $partners[$partnerId]

    $allowedResult = Request-PartnerData `
        -PartnerId $partnerId `
        -DemoUrl $partner.Url `
        -DemoKey $partner.Key `
        -RequestedFields $partner.Fields

    Add-Result `
        -Name "$partnerId allowed request" `
        -Passed (
            $allowedResult.StatusCode -eq 200 `
            -and $allowedResult.Body.result.status -eq "ALLOWED"
        ) `
        -Expected "200 ALLOWED" `
        -Actual "$($allowedResult.StatusCode) $($allowedResult.Body.result.status)"
}

# 5. Sensitive field -> backend DENIED
$sensitiveResult = Request-PartnerData `
    -PartnerId "partner-a" `
    -DemoUrl $partners["partner-a"].Url `
    -DemoKey $partners["partner-a"].Key `
    -RequestedFields @("a", "internalNote")

Add-Result `
    -Name "Sensitive field is denied" `
    -Passed (
        $sensitiveResult.StatusCode -eq 200 `
        -and $sensitiveResult.Body.httpStatusCode -eq 403 `
        -and $sensitiveResult.Body.result.status -eq "DENIED"
    ) `
    -Expected "Wrapper 200, APIM/backend 403 DENIED" `
    -Actual "wrapper=$($sensitiveResult.StatusCode) inner=$($sensitiveResult.Body.httpStatusCode) $($sensitiveResult.Body.result.status)"

# 6. Disabled partner -> 403
$null = Set-Governance `
    -PartnerId "partner-c" `
    -IsActive $false `
    -ExpiryDate "2026-12-31" `
    -QuotaLimit 100

$disabledResult = Verify-Url `
    -PartnerId "partner-c" `
    -DemoUrl $partners["partner-c"].Url

Add-Result `
    -Name "Disabled partner is blocked" `
    -Passed ($disabledResult.StatusCode -eq 403) `
    -Expected "403" `
    -Actual "$($disabledResult.StatusCode)"

# Restore
$null = Set-Governance `
    -PartnerId "partner-c" `
    -IsActive $true `
    -ExpiryDate "2026-12-31" `
    -QuotaLimit 100

# 7. Expired partner -> 403
$null = Set-Governance `
    -PartnerId "partner-d" `
    -IsActive $true `
    -ExpiryDate "2020-01-01" `
    -QuotaLimit 100

$expiredResult = Verify-Url `
    -PartnerId "partner-d" `
    -DemoUrl $partners["partner-d"].Url

Add-Result `
    -Name "Expired partner is blocked" `
    -Passed ($expiredResult.StatusCode -eq 403) `
    -Expected "403" `
    -Actual "$($expiredResult.StatusCode)"

# Restore
$null = Set-Governance `
    -PartnerId "partner-d" `
    -IsActive $true `
    -ExpiryDate "2026-12-31" `
    -QuotaLimit 100

# 8. Quota = 1: first request passes, second is blocked with 429
$null = Set-Governance `
    -PartnerId "partner-g" `
    -IsActive $true `
    -ExpiryDate "2026-12-31" `
    -QuotaLimit 2

$quotaFirst = Request-PartnerData `
    -PartnerId "partner-g" `
    -DemoUrl $partners["partner-g"].Url `
    -DemoKey $partners["partner-g"].Key `
    -RequestedFields @("a")

$quotaSecond = Request-PartnerData `
    -PartnerId "partner-g" `
    -DemoUrl $partners["partner-g"].Url `
    -DemoKey $partners["partner-g"].Key `
    -RequestedFields @("a")

Add-Result `
    -Name "Quota first request passes" `
    -Passed (
        $quotaFirst.StatusCode -eq 200 `
        -and $quotaFirst.Body.result.status -eq "ALLOWED"
    ) `
    -Expected "200 ALLOWED" `
    -Actual "$($quotaFirst.StatusCode) $($quotaFirst.Body.result.status)"

Add-Result `
    -Name "Quota exhausted returns 429" `
    -Passed ($quotaSecond.StatusCode -eq 429) `
    -Expected "429" `
    -Actual "$($quotaSecond.StatusCode)"

# Restore
$null = Set-Governance `
    -PartnerId "partner-g" `
    -IsActive $true `
    -ExpiryDate "2026-12-31" `
    -QuotaLimit 100

# 9. Request history and correlation IDs
$historyResult = Invoke-JsonRequest `
    -Method GET `
    -Path "/ops/api/request-history?key=$([uri]::EscapeDataString($OpsKey))"

$historyItems = @($historyResult.Body.items)
$correlationIds = @(
    $historyItems |
    ForEach-Object { $_.correlationId } |
    Where-Object { $_ }
)

$uniqueIds = @($correlationIds | Sort-Object -Unique)

Add-Result `
    -Name "Request history is populated" `
    -Passed (
        $historyResult.StatusCode -eq 200 `
        -and $historyItems.Count -gt 0
    ) `
    -Expected "200 with at least one item" `
    -Actual "$($historyResult.StatusCode) count=$($historyItems.Count)"

Add-Result `
    -Name "Correlation IDs are unique" `
    -Passed (
        $correlationIds.Count -gt 0 `
        -and $correlationIds.Count -eq $uniqueIds.Count
    ) `
    -Expected "Unique non-empty correlation IDs" `
    -Actual "total=$($correlationIds.Count) unique=$($uniqueIds.Count)"

Write-Host ""
$results | Format-Table -AutoSize

$failed = @($results | Where-Object { $_.Result -eq "FAIL" })

Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "PHASE 9.5 RESULT: PASS" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "PHASE 9.5 RESULT: FAIL ($($failed.Count) failed test(s))" -ForegroundColor Red
    exit 1
}
