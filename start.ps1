# PowerShell 一键启动全套智能 RAG 系统脚本 (Docker 数据服务 + FastAPI API + Worker + Vue 前端)

[CmdletBinding()]
param(
    [switch]$StopDataOnExit  # 退出时是否一并停止 Docker 数据容器 (默认保留后台运行)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 项目各服务根路径配置
$RootDir = $PSScriptRoot
$BackendDir = Join-Path $RootDir "Backend"
$FrontendDir = Join-Path $RootDir "Frontend"
$ComposeFile = Join-Path $BackendDir "docker-compose.yml"
$EnvFile = Join-Path $BackendDir ".env"
$Processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$DataServicesStarted = $false

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "`n[start] $Message" -ForegroundColor Cyan
}

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$InstallHint
    )

    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        throw "未找到命令 '$Name'。$InstallHint"
    }
    return $Command.Source
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    if ($WorkingDirectory) {
        Push-Location $WorkingDirectory
    }
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "命令执行失败（退出码 $LASTEXITCODE）：$FilePath $($ArgumentList -join ' ')"
        }
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$ComposeArguments)

    $Arguments = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)
    $Arguments += $ComposeArguments
    Invoke-CheckedCommand -FilePath $script:DockerCommand -ArgumentList $Arguments
}

function Stop-ApplicationProcesses {
    if ($Processes.Count -eq 0) {
        return
    }

    Write-Step "正在停止前端、API 和 Worker..."
    foreach ($Process in $Processes) {
        try {
            $Process.Refresh()
            if ($Process.HasExited) {
                continue
            }
            if ($env:OS -eq "Windows_NT") {
                & taskkill.exe /PID $Process.Id /T /F *> $null
            }
            else {
                Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        catch {
            Write-Warning "停止进程 $($Process.Id) 时出错：$($_.Exception.Message)"
        }
    }
}

try {
    # 步骤 1：环境检查 (Docker, uv, Node.js)
    $DockerCommand = Get-RequiredCommand -Name "docker" -InstallHint "请先安装并启动 Docker Desktop。"
    $UvCommand = Get-RequiredCommand -Name "uv" -InstallHint "安装说明：https://docs.astral.sh/uv/"
    if ($env:OS -eq "Windows_NT") {
        $NpmCommand = Get-RequiredCommand -Name "npm.cmd" -InstallHint "请先安装 Node.js（其中包含 npm）。"
    }
    else {
        $NpmCommand = Get-RequiredCommand -Name "npm" -InstallHint "请先安装 Node.js（其中包含 npm）。"
    }

    & $DockerCommand info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 守护进程未运行，请先启动 Docker Desktop。"
    }
    & $DockerCommand compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "当前 Docker 未安装 Compose v2 插件。"
    }

    # 步骤 2：校验或自动复制 .env 配置文件
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        $EnvExample = Join-Path $BackendDir ".env.example"
        if (Test-Path -LiteralPath $EnvExample -PathType Leaf) {
            Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
            throw "已创建 Backend/.env，请填写数据库密码、JWT 密钥和模型配置后重新运行。"
        }
        throw "缺少 Backend/.env。"
    }

    # 步骤 3：启动 Docker 数据基础设施服务 (MySQL, Redis, etcd, MinIO, Milvus)
    Write-Step "启动并等待 MySQL、Redis、etcd、MinIO 和 Milvus..."
    $DataServicesStarted = $true
    Invoke-Compose -ComposeArguments @(
        "up", "-d", "--wait", "mysql", "redis", "etcd", "minio", "milvus"
    )

    # 步骤 4：安装 Python 依赖并自动执行 Alembic 数据库迁移
    Write-Step "同步 uv 后端依赖并执行 Alembic 迁移..."
    Invoke-CheckedCommand -FilePath $UvCommand -ArgumentList @("sync") -WorkingDirectory $BackendDir
    Invoke-CheckedCommand -FilePath $UvCommand -ArgumentList @(
        "run", "alembic", "upgrade", "head"
    ) -WorkingDirectory $BackendDir

    # 步骤 5：安装前端 Node 依赖
    $ViteCommand = Join-Path $FrontendDir "node_modules\.bin\vite.cmd"
    if (-not (Test-Path -LiteralPath $ViteCommand -PathType Leaf)) {
        Write-Step "安装前端依赖..."
        Invoke-CheckedCommand -FilePath $NpmCommand -ArgumentList @("ci") -WorkingDirectory $FrontendDir
    }

    # 步骤 6：并发拉起后端 Uvicorn API、后台 Worker 和 Vite 前端服务
    Write-Step "启动 FastAPI、文档 Worker 和 Vue 前端..."
    Write-Host "  前端:    http://localhost:5173"
    Write-Host "  API:     http://localhost:8000"
    Write-Host "  Swagger: http://localhost:8000/docs"
    Write-Host "  Milvus:  http://localhost:9091/healthz"
    Write-Host "  按 Ctrl+C 停止应用进程。"

    $Processes.Add((Start-Process -FilePath $UvCommand -ArgumentList @(
        "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"
    ) -WorkingDirectory $BackendDir -NoNewWindow -PassThru))

    $Processes.Add((Start-Process -FilePath $UvCommand -ArgumentList @(
        "run", "python", "-m", "app.worker"
    ) -WorkingDirectory $BackendDir -NoNewWindow -PassThru))

    $Processes.Add((Start-Process -FilePath $NpmCommand -ArgumentList @(
        "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"
    ) -WorkingDirectory $FrontendDir -NoNewWindow -PassThru))

    # 主挂起循环监控所有子进程健康状态
    while ($true) {
        foreach ($Process in $Processes) {
            $Process.Refresh()
            if ($Process.HasExited) {
                throw "应用进程 $($Process.Id) 已退出，退出码：$($Process.ExitCode)"
            }
        }
        Start-Sleep -Seconds 2
    }
}
catch {
    Write-Host "`n[start] 启动失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Stop-ApplicationProcesses
    if ($DataServicesStarted) {
        if ($StopDataOnExit) {
            Write-Step "正在停止 Docker 数据服务（数据卷会保留）..."
            try {
                Invoke-Compose -ComposeArguments @("stop", "mysql", "redis", "etcd", "minio", "milvus")
            }
            catch {
                Write-Warning $_.Exception.Message
            }
        }
        else {
            Write-Host "[start] Docker 数据服务继续在后台运行。"
        }
    }
}
