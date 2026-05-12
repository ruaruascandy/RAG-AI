param(
    [switch]$WithElectron
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$pythonPath = Join-Path $backendDir ".venv312\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host "未找到后端 Python 环境: $pythonPath" -ForegroundColor Red
    Write-Host "请先在 backend 目录准备 .venv312。" -ForegroundColor Yellow
    exit 1
}

$backendCommand = @"
Set-Location '$backendDir'
`$env:REVIEWER_MODEL='qwen2.5-coder:3b'
`$env:REVIEWER_FALLBACK_MODELS='deepseek-coder:6.7b-instruct-q4_0'
`$env:REVIEWER_TRANSPORT='auto'
`$env:REVIEWER_NUM_CTX='1024'
`$env:REVIEWER_MAX_TOKENS='160'
`$env:REVIEWER_TIMEOUT_SECONDS='45'
`$env:REVIEWER_MAX_RETRIES='2'
`$env:REVIEWER_MAX_CODE_CHARS='5000'
`$env:RAG_EMBED_DEVICE='directml'
`$env:HF_HUB_DISABLE_SYMLINKS='1'
`$env:RAG_HF_HOME='D:\RAG-AI\hf_cache312'
& '$pythonPath' -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"@

$frontendCommand = @"
Set-Location '$frontendDir'
npm.cmd run start
"@

Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    $backendCommand
) | Out-Null

Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    $frontendCommand
) | Out-Null

if ($WithElectron) {
    $electronCommand = @"
Set-Location '$frontendDir'
Start-Sleep -Seconds 8
npm.cmd run electron
"@
    Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $electronCommand
    ) | Out-Null
}

Write-Host "已启动后端(8000)与前端(3000)。" -ForegroundColor Green
if ($WithElectron) {
    Write-Host "Electron 也会自动启动。" -ForegroundColor Green
} else {
    Write-Host "如需 Electron，请运行: .\start-dev.ps1 -WithElectron" -ForegroundColor Yellow
}
