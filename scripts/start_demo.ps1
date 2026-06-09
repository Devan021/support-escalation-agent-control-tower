param(
    [int]$ApiPort = 8000,
    [int]$DashboardPort = 8501
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Streamlit = Join-Path $RepoRoot ".venv\Scripts\streamlit.exe"

if (-not (Test-Path $Python)) {
    throw "Missing virtualenv Python at $Python. Run: python -m venv .venv"
}

if (-not (Test-Path $Streamlit)) {
    throw "Missing Streamlit executable at $Streamlit. Run: .\.venv\Scripts\python.exe -m pip install -e "".[dev]"""
}

$ApiListener = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
$DashboardListener = Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue

if ($ApiListener) {
    Write-Host "FastAPI port $ApiPort already has a listener. No process was stopped."
} else {
    Start-Process -FilePath $Python `
        -ArgumentList "-m uvicorn app.main:app --reload --port $ApiPort" `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden
    Write-Host "Started FastAPI on http://127.0.0.1:$ApiPort"
}

if ($DashboardListener) {
    Write-Host "Streamlit port $DashboardPort already has a listener. No process was stopped."
} else {
    Start-Process -FilePath $Streamlit `
        -ArgumentList "run dashboard\streamlit_app.py --server.port $DashboardPort" `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden
    Write-Host "Started Streamlit on http://127.0.0.1:$DashboardPort"
}

Write-Host "Health: http://127.0.0.1:$ApiPort/health"
Write-Host "Runtime readiness: http://127.0.0.1:$ApiPort/runtime/demo-readiness"
Write-Host "Dashboard: http://127.0.0.1:$DashboardPort"
