param(
    [Parameter(Mandatory = $true)][string]$File,
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Tag = "v1.0"
)
# Upload (clobber) a single release asset to a GitHub release using the
# token stored in Git Credential Manager. The token is never printed.
$ErrorActionPreference = "Stop"
$repo = "TheErsysEnding/teebot-yt-dlp-downloader"
$tag = $Tag

if (-not (Test-Path -LiteralPath $File)) {
    Write-Output "ERROR: file not found: $File"
    exit 1
}

# 1. Pull the GitHub token from Git Credential Manager (no echo).
#    PowerShell 5.1 can't redirect stdin and mangles piped multi-line input,
#    so write the request to a file and feed it to git via cmd redirection.
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

# 2. Look up the release by tag.
$rel = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/tags/$tag"
$relId = $rel.id
Write-Output "release id: $relId"

# 3. Delete any existing asset with the same name (clobber).
foreach ($a in $rel.assets) {
    if ($a.name -eq $Name) {
        Write-Output "deleting existing asset: id=$($a.id) name=$($a.name) size=$($a.size)"
        Invoke-RestMethod -Method Delete -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/assets/$($a.id)" | Out-Null
    }
}

# 4. Upload the new asset (streamed from disk).
$uploadUrl = "https://uploads.github.com/repos/$repo/releases/$relId/assets?name=$Name"
$sizeMB = [Math]::Round((Get-Item -LiteralPath $File).Length / 1MB, 1)
Write-Output "uploading $Name ($sizeMB MB) ..."
$resp = Invoke-RestMethod -Method Post -Headers $headers -ContentType "application/zip" -Uri $uploadUrl -InFile $File -TimeoutSec 3600
Write-Output "OK: name=$($resp.name) state=$($resp.state) size=$($resp.size)"
exit 0
