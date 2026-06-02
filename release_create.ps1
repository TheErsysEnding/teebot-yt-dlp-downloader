param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$NotesFile,
    [string]$Name = ""
)
# Create a GitHub release for an existing tag, using the token in Git
# Credential Manager. The token is never printed.
$ErrorActionPreference = "Stop"
$repo = "TheErsysEnding/teebot-yt-dlp-downloader"
if ([string]::IsNullOrWhiteSpace($Name)) { $Name = "TEE yt-dlp Downloader $Tag" }

if (-not (Test-Path -LiteralPath $NotesFile)) {
    Write-Output "ERROR: notes file not found: $NotesFile"
    exit 1
}

$reqFile = Join-Path $env:TEMP "teebot_cred_req.txt"
Set-Content -LiteralPath $reqFile -Value "protocol=https`nhost=github.com`n`n" -NoNewline -Encoding ascii
$out = cmd /c "git credential fill < `"$reqFile`""
$tok = $null
foreach ($line in $out) { if ($line -like "password=*") { $tok = $line.Substring(9) } }
if ([string]::IsNullOrWhiteSpace($tok)) {
    Write-Output "ERROR: could not obtain token from credential helper"
    exit 1
}

$headers = @{
    Authorization          = "token $tok"
    "User-Agent"           = "teebot-release-script"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$notes = [string](Get-Content -LiteralPath $NotesFile -Raw -Encoding UTF8)
$payload = '{"tag_name":' + (ConvertTo-Json -InputObject $Tag) +
           ',"name":' + (ConvertTo-Json -InputObject $Name) +
           ',"body":' + (ConvertTo-Json -InputObject $notes) +
           ',"draft":false,"prerelease":false}'

$resp = Invoke-RestMethod -Method Post -Headers $headers `
    -ContentType "application/json; charset=utf-8" `
    -Uri "https://api.github.com/repos/$repo/releases" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
Write-Output "OK: release id=$($resp.id) tag=$($resp.tag_name)"
Write-Output "URL: $($resp.html_url)"
exit 0
