#!/usr/bin/env bash

set -euo pipefail

# 这个脚本面向小内存 Ubuntu 机器，优先用 venv 直接跑，避免 Docker 常驻开销。
# 默认行为是重启服务；也支持 start / stop / status / logs。

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$LOG_DIR/opll.pid"
OUT_LOG="$LOG_DIR/opll.out.log"
ERR_LOG="$LOG_DIR/opll.err.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"
ACTION="${1:-restart}"

mkdir -p "$LOG_DIR"

print_step() {
  local index="$1"
  local total="$2"
  local message="$3"
  printf '[%s/%s] %s\n' "$index" "$total" "$message"
}

print_info() {
  printf '%s\n' "$1"
}

find_port_pids() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$PORT" 2>/dev/null || true
    return 0
  fi

  python3 - "$PORT" <<'PY'
import os
import re
import subprocess
import sys

port = sys.argv[1]
try:
    output = subprocess.check_output(["ss", "-ltnp"], text=True, stderr=subprocess.DEVNULL)
except Exception:
    sys.exit(0)

pids = []
for line in output.splitlines():
    if f":{port}" not in line:
        continue
    pids.extend(re.findall(r"pid=(\d+)", line))

if pids:
    print(" ".join(dict.fromkeys(pids)))
PY
}

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi
}

stop_old_service() {
  local stopped=0

  if [[ -f "$PID_FILE" ]]; then
    local pid_from_file
    pid_from_file="$(tr -d '[:space:]' <"$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid_from_file" ]]; then
      stop_pid "$pid_from_file"
      if ! kill -0 "$pid_from_file" 2>/dev/null; then
        print_info "已停止 PID 文件记录的旧进程：$pid_from_file"
        stopped=1
      fi
    fi
    rm -f "$PID_FILE"
  fi

  local port_pids
  port_pids="$(find_port_pids)"
  if [[ -n "$port_pids" ]]; then
    for pid in $port_pids; do
      stop_pid "$pid"
      print_info "已停止占用端口 $PORT 的进程：$pid"
      stopped=1
    done
  fi

  if [[ "$stopped" -eq 0 ]]; then
    print_info "没有发现旧服务。"
  fi
}

ensure_python() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi

  print_info "未找到 python3，请先执行：sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
}

ensure_venv_support() {
  if python3 - <<'PY' >/dev/null 2>&1
import ensurepip
import venv
PY
  then
    return 0
  fi

  local py_minor
  py_minor="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  print_info "当前系统缺少 Python venv 组件。"
  print_info "请先执行：sudo apt update && sudo apt install -y python${py_minor}-venv python3-pip"
  exit 1
}

ensure_venv() {
  ensure_venv_support

  if [[ -x "$PYTHON_BIN" ]] && "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    print_info "已发现 .venv。"
    return 0
  fi

  if [[ -d "$VENV_DIR" ]]; then
    print_info "检测到残缺的 .venv，正在删除后重建..."
    rm -rf "$VENV_DIR"
  fi

  print_info "未发现 .venv，正在创建虚拟环境..."
  python3 -m venv "$VENV_DIR"
}

install_dependencies() {
  print_info "依赖不完整，正在安装 requirements.txt..."
  "$PYTHON_BIN" -m pip install --no-cache-dir -U pip
  if "$PYTHON_BIN" -m pip install --no-cache-dir -r "$REQUIREMENTS_FILE"; then
    return 0
  fi

  # curl_cffi 在部分小机型上可能安装失败，这里退回核心依赖，先保证服务可启动。
  print_info "requirements.txt 安装失败，正在尝试安装精简依赖..."
  "$PYTHON_BIN" -m pip install --no-cache-dir fastapi uvicorn requests pydantic
}

ensure_dependencies() {
  if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import fastapi
import pydantic
import requests
import uvicorn
PY
  then
    print_info "依赖已就绪。"
    return 0
  fi

  install_dependencies
}

health_check() {
  "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import json
import sys
import urllib.request

host = sys.argv[1]
port = sys.argv[2]
url = f"http://{host}:{port}/api/health"

with urllib.request.urlopen(url, timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("health check 返回 ok=false")
PY
}

start_service() {
  : >"$OUT_LOG"
  : >"$ERR_LOG"

  cd "$PROJECT_DIR"
  nohup "$PYTHON_BIN" -m uvicorn app:app --host "$HOST" --port "$PORT" --no-access-log >>"$OUT_LOG" 2>>"$ERR_LOG" &
  local new_pid=$!
  echo "$new_pid" >"$PID_FILE"

  for _ in $(seq 1 20); do
    sleep 1
    if health_check >/dev/null 2>&1; then
      print_info "服务已启动。"
      print_info "访问地址：http://$HOST:$PORT"
      print_info "PID：$new_pid"
      print_info "标准输出日志：$OUT_LOG"
      print_info "错误日志：$ERR_LOG"
      return 0
    fi
  done

  print_info "服务启动失败，请检查日志：$ERR_LOG"
  tail -n 30 "$ERR_LOG" 2>/dev/null || true
  exit 1
}

status_service() {
  if health_check >/dev/null 2>&1; then
    print_info "服务运行中：http://$HOST:$PORT"
    if [[ -f "$PID_FILE" ]]; then
      print_info "PID：$(tr -d '[:space:]' <"$PID_FILE" 2>/dev/null || true)"
    fi
    return 0
  fi

  print_info "服务未运行。"
  return 1
}

show_logs() {
  if [[ -f "$OUT_LOG" ]]; then
    tail -n 50 "$OUT_LOG"
  fi
  if [[ -f "$ERR_LOG" ]]; then
    tail -n 50 "$ERR_LOG"
  fi
}

restart_service() {
  print_step 1 4 "正在检查并停止旧服务..."
  stop_old_service

  print_step 2 4 "正在检查 Python 虚拟环境..."
  ensure_python
  ensure_venv

  print_step 3 4 "正在检查依赖..."
  ensure_dependencies

  print_step 4 4 "正在后台启动服务..."
  start_service
}

case "$ACTION" in
  restart)
    restart_service
    ;;
  start)
    if status_service >/dev/null 2>&1; then
      print_info "服务已经在运行，无需重复启动。"
      exit 0
    fi
    print_step 1 3 "正在检查 Python 虚拟环境..."
    ensure_python
    ensure_venv
    print_step 2 3 "正在检查依赖..."
    ensure_dependencies
    print_step 3 3 "正在后台启动服务..."
    start_service
    ;;
  stop)
    print_step 1 1 "正在停止服务..."
    stop_old_service
    ;;
  status)
    status_service
    ;;
  logs)
    show_logs
    ;;
  *)
    print_info "用法：bash start_restart_opll.sh [restart|start|stop|status|logs]"
    exit 1
    ;;
esac
