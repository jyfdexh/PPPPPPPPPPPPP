$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
if (-not $projectDir) {
    $projectDir = "D:\nanno\Gpt_Plus\转长链\opll"
}

$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$requirements = Join-Path $projectDir "requirements.txt"
$port = 8787

Set-Location -LiteralPath $projectDir

Write-Host "[1/4] 正在检查并停止占用 $port 端口的旧服务..."
$ports = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($ports) {
    $ports | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        if ($_ -and $_ -ne $PID) {
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            Write-Host "已停止旧进程: $_"
        }
    }
} else {
    Write-Host "没有发现旧服务。"
}

Write-Host "[2/4] 正在检查 Python 虚拟环境..."
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Host "未发现 .venv，正在创建虚拟环境..."
    py -m venv (Join-Path $projectDir ".venv")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "创建虚拟环境失败，请确认已安装 Python，并且 py 命令可用。"
        Read-Host "按回车退出"
        exit 1
    }
} else {
    Write-Host "已发现 .venv。"
}

Write-Host "[3/4] 正在检查依赖..."
& $pythonExe -c "import fastapi, uvicorn, requests, curl_cffi, pydantic" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "依赖不完整，正在安装 requirements.txt..."
    & $pythonExe -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Write-Host "安装依赖失败，请检查网络或 pip 输出。"
        Read-Host "按回车退出"
        exit 1
    }
} else {
    Write-Host "依赖已就绪。"
}

Write-Host "[4/4] 正在启动服务..."
Write-Host "访问地址：http://127.0.0.1:$port"
Write-Host "关闭此窗口会停止服务。"
Write-Host ""
& $pythonExe -m uvicorn app:app --host 127.0.0.1 --port $port

Write-Host ""
Write-Host "服务已退出。"
Read-Host "按回车关闭窗口"
