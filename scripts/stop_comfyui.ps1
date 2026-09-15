# 只停止指定 MinimaxH3 仓库和端口的 ComfyUI

param(
    [string]$RepoRoot = '',
    [int]$Port = 8189
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path $PSScriptRoot -Parent }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')
$pattern = [regex]::Escape($RepoRoot)
$targets = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern -and $_.CommandLine -match ('--port\s+' + $Port) }
foreach ($item in $targets) { Stop-Process -Id $item.ProcessId -Force; Write-Host ('已停止 PID ' + $item.ProcessId + '：' + $item.Name) }
if (-not $targets) { Write-Host '没有找到匹配的仓库服务进程。' }
