<#
.SYNOPSIS
  Guided one-click deploy for University Helper on Windows (Docker Desktop).

.DESCRIPTION
  Writes or updates .env (random secrets on the first run; existing secrets are
  kept), pulls the prebuilt images (or builds from source with -Build), starts
  app + postgres + web via Docker Compose, waits for health, and prints the
  access URL. TLS/host-nginx setup is a Linux-server concern and is out of
  scope here: put this behind a reverse proxy (or use a Linux box with
  scripts/deploy_server.sh) for a public HTTPS deployment.

  Works from a git checkout, or on its own: when docker-compose.release.yml and
  database/ are not next to it, it downloads the matching source release first.

.EXAMPLE
  pwsh scripts/deploy_server.ps1 -Port 8080
.EXAMPLE
  pwsh scripts/deploy_server.ps1 -HostIp 192.168.1.50 -AdminEmail you@example.com -Yes
.EXAMPLE
  Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
  powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes
#>
[CmdletBinding()]
param(
  [string]$Domain = "",
  [string]$HostIp = "",
  [int]$Port = 8080,
  [string]$Tag = "latest",
  [string]$AdminEmail = "",
  [string]$AllowedHosts = "",
  [switch]$Build,
  [switch]$Yes
)

$ErrorActionPreference = "Stop"

# Release CI stamps the tag into the copy attached to each GitHub release.
$BundledTag = ""

$RepoSlug    = "sweetcornna/university-helper"
$Project     = "university-helper"
$ComposeFile = "docker-compose.release.yml"
$ImageNs     = "ghcr.io/sweetcornna"
$DbVolume    = "${Project}_shuake-postgres-data"
$BuildNpmReg = "https://registry.npmmirror.com"
$BoundParams = @{} + $PSBoundParameters
$TagProvided = $PSBoundParameters.ContainsKey("Tag")
$PortProvided = $PSBoundParameters.ContainsKey("Port")
$AdminProvided = $PSBoundParameters.ContainsKey("AdminEmail")
$AllowedProvided = $PSBoundParameters.ContainsKey("AllowedHosts")

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!] $m"  -ForegroundColor Yellow }
function Die($m)  { Write-Host "[x] $m"  -ForegroundColor Red; exit 1 }
function Normalize-ImageTag([string]$RawTag) {
  if ([string]::IsNullOrWhiteSpace($RawTag)) { return "latest" }
  if ($RawTag -match '^v(?=\d)') { return $RawTag.Substring(1) }
  return $RawTag
}

function Validate-Domain([string]$Value) {
  # Keep this diagnostic constant: domain input may contain control characters.
  $FqdnPattern = '\A[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+\z'
  if (
    [string]::IsNullOrEmpty($Value) -or
    $Value.Length -gt 253 -or
    -not [Regex]::IsMatch($Value, $FqdnPattern, [Text.RegularExpressions.RegexOptions]::CultureInvariant)
  ) {
    Die "Invalid --domain: expected an ASCII FQDN (for example example.com)."
  }

  foreach ($label in ($Value -split '\.')) {
    if ($label.Length -gt 63) {
      Die "Invalid --domain: expected an ASCII FQDN (for example example.com)."
    }
  }
}

$DomainProvided = $PSBoundParameters.ContainsKey("Domain")
if ($DomainProvided) {
  Validate-Domain $Domain
}

# ---- other inputs (validated before anything touches disk or docker) --------
if ($HostIp -and -not [Regex]::IsMatch($HostIp, '\A[A-Za-z0-9.:-]+\z')) {
  Die "Invalid -HostIp: expected an IP address or hostname."
}
if ($Port -lt 1 -or $Port -gt 65535) {
  Die "Invalid -Port: expected a number between 1 and 65535."
}
$AdminEmail = $AdminEmail -replace '\s', ''
if ($AdminEmail) {
  foreach ($email in ($AdminEmail -split ',')) {
    if (-not [Regex]::IsMatch($email, '\A[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z0-9-]+\z')) {
      Die "Invalid -AdminEmail: expected one or more email addresses separated by commas."
    }
  }
}
$AllowedHosts = $AllowedHosts -replace '\s', ''
if ($AllowedHosts -and -not [Regex]::IsMatch($AllowedHosts, '\A[A-Za-z0-9.*:,-]+\z')) {
  Die "Invalid -AllowedHosts: expected hostnames or IPs separated by commas."
}

# ---- locate (or download) the deployment files -----------------------------
function Test-CompleteRoot([string]$Dir) {
  if (-not $Dir) { return $false }
  foreach ($rel in @($ComposeFile, "database/00-schema.sql", "database/02-bootstrap-tenant-template.sh", "database/templates/tenant_template.sql")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Dir $rel) -PathType Leaf)) { return $false }
  }
  return $true
}

function Save-SourceRelease([string]$SourceTag, [string]$Target) {
  if (-not [Regex]::IsMatch($SourceTag, '\Av\d+\.\d+\.\d+([-+.][0-9A-Za-z.-]+)?\z')) {
    Die "Could not determine which release to download (got '$SourceTag'). Pass -Tag, e.g. -Tag 1.4.7."
  }
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("uh-source-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $tmp -Force | Out-Null
  $zip = Join-Path $tmp "source.zip"
  try {
    Invoke-WebRequest -UseBasicParsing -OutFile $zip "https://github.com/$RepoSlug/archive/refs/tags/$SourceTag.zip"
  } catch {
    Die "Download failed: https://github.com/$RepoSlug/archive/refs/tags/$SourceTag.zip"
  }
  Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp "src") -Force
  $top = Get-ChildItem -LiteralPath (Join-Path $tmp "src") -Directory | Select-Object -First 1
  New-Item -ItemType Directory -Path $Target -Force | Out-Null
  # The archive never contains .env, so an existing configuration is kept.
  Copy-Item -Path (Join-Path $top.FullName '*') -Destination $Target -Recurse -Force
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Set-Content -LiteralPath (Join-Path $Target ".uh-source-tag") -Value $SourceTag -Encoding ascii
  if (-not (Test-CompleteRoot $Target)) {
    Die "The downloaded source is incomplete: $ComposeFile or database/ is missing."
  }
  Ok "Source ready in $Target"
}

function Invoke-DownloadedScript([string]$Target, [string]$SourceTag) {
  $childArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Target "scripts/deploy_server.ps1"))
  foreach ($entry in $BoundParams.GetEnumerator()) {
    if ($entry.Value -is [System.Management.Automation.SwitchParameter]) {
      if ($entry.Value.IsPresent) { $childArgs += "-$($entry.Key)" }
    } else {
      $childArgs += "-$($entry.Key)"
      $childArgs += [string]$entry.Value
    }
  }
  if (-not $TagProvided) { $childArgs += @("-Tag", $SourceTag) }
  $env:UH_BOOTSTRAPPED = "1"
  $hostExe = (Get-Process -Id $PID).Path
  & $hostExe @childArgs
  exit $LASTEXITCODE
}

function Invoke-SourceBootstrap {
  if ($env:UH_BOOTSTRAPPED -eq "1") {
    Die "The downloaded source is incomplete: $ComposeFile or database/ is missing."
  }
  if ($env:UH_DEPLOY_OFFLINE -eq "1") {
    Die "$ComposeFile and database/ were not found next to this script, and UH_DEPLOY_OFFLINE=1 forbids downloading them. Run the script from a full checkout."
  }

  $sourceTag = $Tag
  if (-not $TagProvided -or $sourceTag -eq "latest") { $sourceTag = $BundledTag }
  if (-not $sourceTag) {
    try {
      $sourceTag = (Invoke-RestMethod -UseBasicParsing -TimeoutSec 20 "https://api.github.com/repos/$RepoSlug/releases/latest").tag_name
    } catch {
      Die "Could not look up the latest release on GitHub (no network?). Pass -Tag or run from a git checkout."
    }
  }
  if (-not [Regex]::IsMatch([string]$sourceTag, '\Av?\d+\.\d+\.\d+([-+.][0-9A-Za-z.-]+)?\z')) {
    Die "Could not determine which release to download (got '$sourceTag'). Pass -Tag, e.g. -Tag 1.4.7."
  }
  if (-not $sourceTag.StartsWith("v")) { $sourceTag = "v$sourceTag" }

  $target = if ($env:UH_INSTALL_DIR) { $env:UH_INSTALL_DIR } else { Join-Path (Get-Location).Path "university-helper" }
  Info "Deployment files not found here; downloading University Helper $sourceTag into $target ..."
  Save-SourceRelease $sourceTag $target
  Invoke-DownloadedScript $target $sourceTag
}

# Updating an install means new compose files and scripts as well as new
# images. A directory this script downloaded (it has .uh-source-tag) is moved to
# the requested release first; a git checkout is the user's to update.
function Update-SourceIfOutdated([string]$Root) {
  $wanted = ""
  if ($TagProvided -and $Tag -ne "latest") { $wanted = $Tag } elseif ($BundledTag) { $wanted = $BundledTag }
  if (-not $wanted) { return }
  if (-not $wanted.StartsWith("v")) { $wanted = "v$wanted" }

  $marker = Join-Path $Root ".uh-source-tag"
  if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    $pyproject = Join-Path $Root "backend/pyproject.toml"
    if ((Test-Path -LiteralPath (Join-Path $Root ".git")) -and (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
      $match = Select-String -LiteralPath $pyproject -Pattern '^version = "(.*)"$' | Select-Object -First 1
      if ($match -and "v$($match.Matches[0].Groups[1].Value)" -ne $wanted) {
        Warn "This git checkout is version $($match.Matches[0].Groups[1].Value), but you asked for $wanted. Compose files and scripts come from the checkout; run 'git fetch --tags; git checkout $wanted' first to match them."
      }
    }
    return
  }
  if ($env:UH_BOOTSTRAPPED -eq "1") { return }

  $current = (Get-Content -LiteralPath $marker -Raw).Trim()
  if ($current -eq $wanted) { return }
  if ($env:UH_DEPLOY_OFFLINE -eq "1") {
    Warn "UH_DEPLOY_OFFLINE=1: keeping the $current deployment files while deploying $wanted images."
    return
  }
  Info "Updating the deployment files in $Root from $current to $wanted ..."
  Save-SourceRelease $wanted $Root
  Invoke-DownloadedScript $Root $wanted
}

$Candidates = @()
if ($PSScriptRoot) { $Candidates += @((Split-Path -Parent $PSScriptRoot), $PSScriptRoot) }
$Candidates += @((Get-Location).Path, (Join-Path (Get-Location).Path "university-helper"))
$RepoRoot = $null
foreach ($candidate in $Candidates) {
  if (Test-CompleteRoot $candidate) { $RepoRoot = (Resolve-Path -LiteralPath $candidate).Path; break }
}
if (-not $RepoRoot) { Invoke-SourceBootstrap }
Update-SourceIfOutdated $RepoRoot

Set-Location $RepoRoot

function New-HexSecret([int]$Bytes = 32) {
  $b = New-Object byte[] $Bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  ($b | ForEach-Object { $_.ToString('x2') }) -join ''
}
function New-FernetKey {
  # urlsafe-base64 of 32 random bytes == cryptography.fernet.Fernet.generate_key()
  $b = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  ([Convert]::ToBase64String($b)).Replace('+', '-').Replace('/', '_')
}

$RawTag = $Tag
$ImageTag = Normalize-ImageTag $Tag
if ($ImageTag -ne $RawTag) {
  Warn "Normalizing release tag $RawTag -> $ImageTag for GHCR image tags."
}

Info "University Helper guided deploy (Windows) — mode: $(if ($Build) {'build'} else {'pull'}), tag: $ImageTag"

$HttpBindHost = if ($HostIp -and -not $Domain) { "0.0.0.0" } else { "127.0.0.1" }
$AppPort = "8000"

# ---- docker + compose -----------------------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Die "Docker not found. Install Docker Desktop (https://docs.docker.com/desktop/windows/) and re-run."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { Die "Docker Desktop is not running. Start it and re-run." }
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Die "Docker Compose v2 is required (ships with Docker Desktop)." }
function Compose { docker compose -p $Project -f $ComposeFile @args }
Ok "Docker + compose ready"

function Test-DbVolume {
  docker volume inspect $DbVolume *> $null
  return ($LASTEXITCODE -eq 0)
}

# ---- .env -----------------------------------------------------------------
function Get-EnvValue([string]$Key) {
  if (-not (Test-Path -LiteralPath ".env")) { return "" }
  $line = @(Get-Content -LiteralPath ".env") | Where-Object { $_ -like "$Key=*" } | Select-Object -Last 1
  if ($null -eq $line) { return "" }
  return $line.Substring($Key.Length + 1)
}
function Test-EnvKey([string]$Key) {
  if (-not (Test-Path -LiteralPath ".env")) { return $false }
  return [bool](@(Get-Content -LiteralPath ".env") | Where-Object { $_ -like "$Key=*" })
}
function Set-EnvValue([string]$Key, [string]$Value) {
  $done = $false
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($line in @(Get-Content -LiteralPath ".env")) {
    if ($line -like "$Key=*") {
      if (-not $done) { $out.Add("$Key=$Value"); $done = $true }
    } else {
      $out.Add($line)
    }
  }
  if (-not $done) { $out.Add("$Key=$Value") }
  [IO.File]::WriteAllText((Join-Path (Get-Location).Path ".env"), (($out -join "`n") + "`n"))
}
function Test-Placeholder([string]$Value) {
  return (-not $Value) -or $Value.StartsWith("change-this") -or $Value.StartsWith("replace-with")
}
function Get-DefaultCors {
  if ($Domain) { return "[`"https://$Domain`"]" }
  if ($HostIp) { return "[`"http://${HostIp}:$Port`"]" }
  return "[`"http://localhost:$Port`",`"http://127.0.0.1:$Port`"]"
}
function Get-DefaultEnvTag { if ($Domain) { "production" } else { "dev" } }

$ExplicitSite = $DomainProvided -or [bool]$HostIp
if (-not (Test-Path ".env")) {
  if (Test-DbVolume) {
    Die "Found the database volume $DbVolume but no .env. Restore the .env you backed up (it holds the database password and CREDENTIAL_ENCRYPTION_KEY); new secrets would lock you out of the existing data."
  }
  Info "Generating .env with fresh secrets…"
  $EnvTag = Get-DefaultEnvTag
  $Cors = Get-DefaultCors
  if ($Domain) {
  } elseif ($HostIp) {
    Warn "No -Domain: deploying http-only on ${HostIp}:$Port (ENV=dev)."
  } else {
    Warn "No -Domain/-HostIp: deploying for local access only (http://localhost:$Port)."
  }
  $envBody = @"
# Generated by scripts/deploy_server.ps1 — do NOT commit. Back up this file:
# losing CREDENTIAL_ENCRYPTION_KEY makes stored credentials unrecoverable, and
# losing POSTGRES_PASSWORD locks you out of the data.
POSTGRES_PASSWORD=$(New-HexSecret 24)
SECRET_KEY=$(New-HexSecret 32)
SHUAKE_COMPAT_SECRET=
CREDENTIAL_ENCRYPTION_KEY=$(New-FernetKey)
CORS_ORIGINS=$Cors
ALLOWED_HOSTS=$AllowedHosts
ADMIN_EMAILS=$AdminEmail
ENV=$EnvTag
APP_PORT=$AppPort
HTTP_PORT=$Port
HTTP_BIND_HOST=$HttpBindHost

"@
  Set-Content -Path ".env" -Value $envBody -NoNewline -Encoding ascii
  if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) { chmod 600 .env }
  Ok ".env written (ENV=$EnvTag, CORS=$Cors)"
} else {
  Info "Updating existing .env (secrets are kept)…"
  $value = Get-EnvValue "POSTGRES_PASSWORD"
  if (-not $value) {
    if (Test-DbVolume) {
      Die "POSTGRES_PASSWORD is empty in .env but the database volume $DbVolume already exists. Restore the password from your .env backup; a new one cannot open the existing data."
    }
    Set-EnvValue "POSTGRES_PASSWORD" (New-HexSecret 24)
    Ok "Generated POSTGRES_PASSWORD."
  } elseif (Test-Placeholder $value) {
    if (Test-DbVolume) {
      Warn "POSTGRES_PASSWORD is still the example value; the existing database uses it, so it is kept."
    } else {
      Set-EnvValue "POSTGRES_PASSWORD" (New-HexSecret 24)
      Ok "Replaced the example POSTGRES_PASSWORD with a random one."
    }
  }
  $value = Get-EnvValue "SECRET_KEY"
  if ((Test-Placeholder $value) -or $value.Length -lt 32) {
    Set-EnvValue "SECRET_KEY" (New-HexSecret 32)
    Warn "SECRET_KEY was missing, an example value or too short; generated a new one (existing logins must sign in again)."
  }
  $value = Get-EnvValue "CREDENTIAL_ENCRYPTION_KEY"
  if (Test-Placeholder $value) {
    Set-EnvValue "CREDENTIAL_ENCRYPTION_KEY" (New-FernetKey)
    Warn "Generated CREDENTIAL_ENCRYPTION_KEY. Back up .env: losing this key makes stored platform credentials unrecoverable."
  } elseif (-not [Regex]::IsMatch($value, '\A[A-Za-z0-9_-]{43}=\z')) {
    Die "CREDENTIAL_ENCRYPTION_KEY in .env is not a valid Fernet key (44 characters of urlsafe base64). Fix it by hand; replacing it would make stored credentials unreadable."
  }
  if (-not (Test-EnvKey "SHUAKE_COMPAT_SECRET")) { Set-EnvValue "SHUAKE_COMPAT_SECRET" "" }

  # Network settings: options passed now win, otherwise keep what .env has.
  if ($PortProvided -or -not (Get-EnvValue "HTTP_PORT")) { Set-EnvValue "HTTP_PORT" "$Port" } else { $Port = [int](Get-EnvValue "HTTP_PORT") }
  if (-not (Get-EnvValue "APP_PORT")) { Set-EnvValue "APP_PORT" $AppPort } else { $AppPort = Get-EnvValue "APP_PORT" }
  if ($ExplicitSite -or -not (Get-EnvValue "HTTP_BIND_HOST")) { Set-EnvValue "HTTP_BIND_HOST" $HttpBindHost } else { $HttpBindHost = Get-EnvValue "HTTP_BIND_HOST" }
  if ($ExplicitSite -or -not (Get-EnvValue "CORS_ORIGINS")) { Set-EnvValue "CORS_ORIGINS" (Get-DefaultCors) }
  if ($ExplicitSite -or -not (Get-EnvValue "ENV")) { Set-EnvValue "ENV" (Get-DefaultEnvTag) }
  if ($AllowedProvided) { Set-EnvValue "ALLOWED_HOSTS" $AllowedHosts } elseif (-not (Test-EnvKey "ALLOWED_HOSTS")) { Set-EnvValue "ALLOWED_HOSTS" "" }
  if ($AdminProvided) { Set-EnvValue "ADMIN_EMAILS" $AdminEmail } elseif (-not (Test-EnvKey "ADMIN_EMAILS")) { Set-EnvValue "ADMIN_EMAILS" "" }
  Ok ".env updated (ENV=$(Get-EnvValue 'ENV'), CORS=$(Get-EnvValue 'CORS_ORIGINS'))"
}

$EnvTagNow = Get-EnvValue "ENV"
if ($EnvTagNow -eq "production" -or $EnvTagNow -eq "prod") {
  foreach ($origin in ((Get-EnvValue "CORS_ORIGINS") -split ',')) {
    if ($origin -match 'http://' -and $origin -notmatch 'localhost') {
      Die "ENV=production requires https:// CORS_ORIGINS. Re-run with -Domain <your.domain>, or with -HostIp <ip> for plain http."
    }
  }
}

# ---- bring up the stack ---------------------------------------------------
$env:HTTP_PORT = "$Port"
$env:APP_PORT  = "$AppPort"
$env:HTTP_BIND_HOST = $HttpBindHost

function Build-Images {
  Info "Building images from source (this can take a few minutes)…"
  docker build -f Dockerfile.server -t "$ImageNs/university-helper-app:local" .
  if ($LASTEXITCODE -ne 0) { Die "docker build of the app image failed (exit code $LASTEXITCODE)." }
  docker build -f Dockerfile.web --build-arg "NPM_REGISTRY=$BuildNpmReg" -t "$ImageNs/university-helper-web:local" .
  if ($LASTEXITCODE -ne 0) { Die "docker build of the web image failed (exit code $LASTEXITCODE)." }
  $env:UH_TAG = "local"
}

if ($Build) {
  Build-Images
} else {
  $env:UH_TAG = $ImageTag
  Info "Pulling images $ImageNs/university-helper-{app,web}:$ImageTag…"
  Compose pull
  if ($LASTEXITCODE -ne 0) {
    Warn "Pull failed (images may not be published yet, or no network)."
    if (-not $Yes) { Die "Aborting. Re-run with -Build to build locally, or with -Yes to fall back automatically." }
    Build-Images
  }
}
Info "Starting stack…"
Compose up -d
if ($LASTEXITCODE -ne 0) {
  Warn "Containers:"
  Compose ps
  Warn "Recent logs:"
  Compose logs --tail=80 app postgres
  Die "The stack did not start. Fix the error above and re-run this script; .env and the database are kept."
}

# ---- health ---------------------------------------------------------------
$healthUrl = "http://127.0.0.1:$Port/health"
Info "Waiting for health at $healthUrl …"
$healthy = $false
foreach ($i in 1..60) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 $healthUrl
    if ($response -and $response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
      $healthy = $true; break
    }
  } catch { Start-Sleep -Seconds 2 }
}
if ($healthy) {
  Ok "App is healthy."
} else {
  Die "Health check timed out or never returned a 2xx response. Check: docker compose -p $Project -f $ComposeFile logs --tail=80 app"
}

# Registration needs the users table and tenant_template; /health reports both.
$schemaBody = ""
foreach ($i in 1..15) {
  try {
    $schemaBody = [string](Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 $healthUrl).Content
  } catch { $schemaBody = "" }
  if (-not $schemaBody -or $schemaBody -notmatch '"schema":') { $schemaBody = ""; break }
  if ($schemaBody -match '"schema":"ok"') { Ok "Database ready for registration (users table + tenant_template)."; $schemaBody = ""; break }
  Start-Sleep -Seconds 2
}
if ($schemaBody) {
  Warn "The database is not ready for registration yet: $schemaBody"
  Warn "The app repairs this on start. If sign-up keeps failing, check: docker compose -p $Project -f $ComposeFile logs --tail=80 app postgres"
}

# ---- summary --------------------------------------------------------------
Write-Host ""
Ok "Deploy complete."
if ($Domain)      { Write-Host "  Access:  https://$Domain  (front it with your own TLS reverse proxy)" }
elseif ($HostIp)  { Write-Host "  Access:  http://${HostIp}:$Port" }
else              { Write-Host "  Access:  http://localhost:$Port" }
$Admins = Get-EnvValue "ADMIN_EMAILS"
Write-Host "  Admin:   $(if ($Admins) { $Admins } else { 'the first account that registers' })"
Write-Host "  Manage:  docker compose -p $Project -f $ComposeFile ps | logs -f app | down"
Write-Host "  Update:  powershell -ExecutionPolicy Bypass -File scripts/deploy_server.ps1 -Tag <new version> -Yes   (keeps .env and data)"
