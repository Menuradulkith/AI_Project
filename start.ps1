# start.ps1  –  Launch the full IFS Jira Dashboard in one command
# Run from: c:\IFS_WORK\AI_Project\
#   powershell -ExecutionPolicy Bypass -File start.ps1

$root      = $PSScriptRoot
$backend   = "$root\backend"
$python    = "$backend\.venv\Scripts\python.exe"
$api       = "$backend\api.py"
$dashboard = "$root\dashboard"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   IFS Jira Dashboard — Starting Up     " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check python venv exists ─────────────────────────────────────────────
if (-not (Test-Path $python)) {
    Write-Host "ERROR: Virtual environment not found at $python" -ForegroundColor Red
    Write-Host "Run:  python -m venv backend\.venv  then  backend\.venv\Scripts\pip install -r backend\requirements.txt" -ForegroundColor Yellow
    exit 1
}

# ── Check .env exists ───────────────────────────────────────────────────────
if (-not (Test-Path "$backend\.env")) {
    Write-Host "ERROR: .env file not found in backend/. Copy backend/.env.example to backend/.env and fill in credentials." -ForegroundColor Red
    exit 1
}

# ── Check node_modules ────────────────────────────────────────────
if (-not (Test-Path "$dashboard\node_modules")) {
    Write-Host "Installing Node dependencies..." -ForegroundColor Yellow
    Push-Location $dashboard
    npm install
    Pop-Location
}

Write-Host "Starting Flask API on  http://localhost:5001 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "Write-Host 'Flask API' -ForegroundColor Cyan; Set-Location '$backend'; & '$python' '$api'"

Start-Sleep -Seconds 2

Write-Host "Starting React Dashboard on  http://localhost:5173 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "Write-Host 'React Dashboard' -ForegroundColor Cyan; Set-Location '$dashboard'; npm run dev"

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Both servers are starting up!"          -ForegroundColor White
Write-Host ""
Write-Host "  Flask API  →  http://localhost:5001"    -ForegroundColor Green
Write-Host "  Dashboard  →  http://localhost:5173"    -ForegroundColor Green
Write-Host ""
Write-Host "  Close the two new PowerShell windows"   -ForegroundColor Yellow
Write-Host "  to stop the servers."                   -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
