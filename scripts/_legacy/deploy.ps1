$ErrorActionPreference = "Stop"

$Server = $env:EASY_LEARNING_SERVER
if ([string]::IsNullOrWhiteSpace($Server)) {
    throw "Missing EASY_LEARNING_SERVER. Example: `$env:EASY_LEARNING_SERVER='root@example.com'"
}

$ProjectName = if ([string]::IsNullOrWhiteSpace($env:EASY_LEARNING_PROJECT_NAME)) { "easy_learning" } else { $env:EASY_LEARNING_PROJECT_NAME }
$RemoteDir = if ([string]::IsNullOrWhiteSpace($env:EASY_LEARNING_REMOTE_DIR)) { "/opt/$ProjectName" } else { $env:EASY_LEARNING_REMOTE_DIR }
$ComposeFile = if ([string]::IsNullOrWhiteSpace($env:EASY_LEARNING_COMPOSE_FILE)) { "docker-compose.server.yml" } else { $env:EASY_LEARNING_COMPOSE_FILE }
$DbPassword = if ([string]::IsNullOrWhiteSpace($env:EASY_LEARNING_POSTGRES_PASSWORD)) { "change-this-db-password" } else { $env:EASY_LEARNING_POSTGRES_PASSWORD }
$SecretKey = if ([string]::IsNullOrWhiteSpace($env:EASY_LEARNING_SECRET_KEY)) { -join ((48..57) + (97..102) | Get-Random -Count 64 | ForEach-Object {[char]$_}) } else { $env:EASY_LEARNING_SECRET_KEY }
$CompatSecret = $env:EASY_LEARNING_SHUAKE_COMPAT_SECRET
$CorsOrigins = if ([string]::IsNullOrWhiteSpace($env:EASY_LEARNING_CORS_ORIGINS)) { '["http://localhost:3000","http://localhost:5173"]' } else { $env:EASY_LEARNING_CORS_ORIGINS }

$TempEnv = [System.IO.Path]::GetTempFileName()
@"
POSTGRES_PASSWORD=$DbPassword
SECRET_KEY=$SecretKey
SHUAKE_COMPAT_SECRET=$CompatSecret
CORS_ORIGINS=$CorsOrigins
"@ | Set-Content -Path $TempEnv -Encoding UTF8

try {
    Write-Host "Uploading project to $Server`:$RemoteDir"
    & ssh $Server "mkdir -p '$RemoteDir'"
    & rsync -avz --exclude node_modules --exclude .git --exclude dist --exclude __pycache__ --exclude .pytest_cache --exclude %TEMP% ./ "$Server`:$RemoteDir/"
    & scp $TempEnv "$Server`:$RemoteDir/.env"

    Write-Host "Starting deployment with $ComposeFile"
    & ssh $Server "cd '$RemoteDir' && docker compose -f '$ComposeFile' down || true"
    & ssh $Server "cd '$RemoteDir' && docker compose -f '$ComposeFile' up -d --build"
    & ssh $Server "cd '$RemoteDir' && docker compose -f '$ComposeFile' ps"
}
finally {
    Remove-Item -Path $TempEnv -Force -ErrorAction SilentlyContinue
}
