# 一键初始化 .venv 并以可编辑模式安装 StockWindow 与测试依赖
param(
    [string]$IndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[1/3] 正在创建 Python 虚拟环境 (.venv)..."
    python -m venv .venv
}

Write-Host "[2/3] 正在安装运行与开发依赖..."
.\.venv\Scripts\pip.exe install -i $IndexUrl --upgrade setuptools wheel
.\.venv\Scripts\pip.exe install -i $IndexUrl -r requirements-dev.txt

Write-Host "[3/3] 正在以可编辑模式安装 stock-window 包..."
.\.venv\Scripts\pip.exe install --no-build-isolation --no-deps -e .

Write-Host "环境初始化完成！可执行 .\scripts\start.ps1 启动。"
