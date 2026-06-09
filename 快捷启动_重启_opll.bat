@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
set "OPENAI_PAY_UI_PROFILE=local"
set "OPENAI_PAY_DEFAULT_PROXY=http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"
set "OPENAI_PAY_LOCAL_PROXY=http://bj2m1188418-region-JP:nanno2@127.0.0.1:3010"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); $script = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path '%SCRIPT_DIR%' 'start_restart_opll.ps1'))); Invoke-Command ([ScriptBlock]::Create($script))"
