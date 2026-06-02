param(
    [Parameter(Mandatory = $true)][string]$NotesFile
)
# Update the v1.0 GitHub release body from a notes file, using the token in
# Git Credential Manager. The token is never printed.
$ErrorActionPreference = "Stop"
$repo = "TheErsysEnding/teebot-yt-dlp-downloader"
$tag = "v1.0"

if (-not (Test-Path -LiteralPath $NotesFile)) {
    Write-Output "ERROR: notes file not found: $NotesFile"
    exit 1
}

# Token from Git Credential Manager (via cmd stdin redirection).
$reqFile = Join-Path $env:TEMP "teebot_cred_req.txt"
Set-Content -LiteralPath $reqFile -Value "protocol=https`nhost=github.com`n`n" -NoNewline -Encoding ascii
$out = cmd /c "git credential fill < `"$reqFile`""
$tok = $null
foreach ($line in $out) {
    if ($line -like "password=*") { $tok = $line.Substring(9) }
}
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

$rel = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/tags/$tag"
$relId = $rel.id

$notes = [string](Get-Content -LiteralPath $NotesFile -Raw -Encoding UTF8)
# Encode just the string value (reliable JSON escaping), then wrap manually.
# (ConvertTo-Json on a hashtable mis-serialized the string into a huge object.)
$jsonBody = ConvertTo-Json -InputObject $notes
$payload = '{"body":' + $jsonBody + '}'

$resp = Invoke-RestMethod -Method Patch -Headers $headers -ContentType "application/json; charset=utf-8" `
    -Uri "https://api.github.com/repos/$repo/releases/$relId" -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
Write-Output "OK: release $($resp.tag_name) body updated ($($notes.Length) chars)"
exit 0
