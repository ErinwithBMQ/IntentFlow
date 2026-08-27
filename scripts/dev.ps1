$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$serverRoot = Join-Path $workspaceRoot "server"
$webRoot = Join-Path $workspaceRoot "web"
$serverPython = Join-Path $serverRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $serverPython)) {
    throw "Python virtual environment not found. Initialize server/.venv first; see README.md."
}

$serverJob = Start-Job -ScriptBlock {
    param($workingDirectory, $pythonPath)
    Set-Location -LiteralPath $workingDirectory
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000
} -ArgumentList $serverRoot, $serverPython

try {
    Set-Location -LiteralPath $webRoot
    npm run dev
}
finally {
    Stop-Job -Job $serverJob -ErrorAction SilentlyContinue
    Receive-Job -Job $serverJob -ErrorAction SilentlyContinue
    Remove-Job -Job $serverJob -Force -ErrorAction SilentlyContinue

    $listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process.CommandLine -like "*$serverRoot*uvicorn*app.main:app*") {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}
