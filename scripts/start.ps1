# 后台无黑框启动 StockWindow（使用 .venv 中的 pythonw.exe）
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $PythonW)) {
    Write-Error "未找到 .venv，请先执行 .\scripts\setup.ps1 初始化环境。"
    exit 1
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
Start-Process -FilePath $PythonW -ArgumentList "-m", "stock_window" -WorkingDirectory $ProjectRoot
Write-Host "StockWindow 已在后台启动（右键任务栏左下角股票条或托盘图标即可管理自选与外观）。"
