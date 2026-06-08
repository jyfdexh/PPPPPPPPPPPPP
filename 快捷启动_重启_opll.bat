@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); $script = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path '%SCRIPT_DIR%' 'start_restart_opll.ps1'))); Invoke-Command ([ScriptBlock]::Create($script))"
