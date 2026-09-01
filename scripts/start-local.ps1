$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$envFile = Join-Path $repoRoot '.env'

# Web service bind used to launch main.py and to open the browser.
$hostName = '127.0.0.1'
$port = 8000
$webuiUrl = "http://${hostName}:${port}"

if (!(Test-Path $python)) {
  throw 'Project virtual environment not found. Run: py -3.14 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}
if (!(Test-Path $envFile)) {
  Copy-Item (Join-Path $repoRoot '.env.example') $envFile
  Write-Host 'Created .env from .env.example. Local Ollama settings were not added automatically.' -ForegroundColor Yellow
}

Write-Host 'Starting Daily Stock Analysis API. Ollama is not started or loaded at launch; activate it from Settings > AI when needed.' -ForegroundColor Green

# Open the Web UI in the default browser once the server is reachable. This runs
# in a background job so the API server stays in the foreground: logs remain
# visible in this window and Ctrl+C still stops the server.
$webuiOpener = Start-Job -ScriptBlock {
  param($url, $timeoutSeconds)
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  $opened = $false
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -eq 200) {
        Start-Process $url
        $opened = $true
        break
      }
    } catch {
      # Server not ready yet; keep polling.
    }
    Start-Sleep -Milliseconds 1000
  }
  if (-not $opened) {
    Write-Warning "Timed out waiting for Web UI at $url after $timeoutSeconds seconds."
  }
} -ArgumentList $webuiUrl, 240

try {
  & $python main.py --serve-only --host $hostName --port $port
} finally {
  Stop-Job $webuiOpener -ErrorAction SilentlyContinue
  Remove-Job $webuiOpener -Force -ErrorAction SilentlyContinue
}
