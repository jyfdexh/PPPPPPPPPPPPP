#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_FILE="${CONFIG_FILE:-/etc/opll-deploy.env}"
FORCE="${FORCE:-no}"

APP_DIR="/opt/opll"
APP_USER="opll"
APP_HOST="0.0.0.0"
APP_PORT="8787"
SERVICE_NAME="opll"
BRANCH="main"

log() {
  printf '\n\033[1;32m%s\033[0m\n' "$1"
}

fail() {
  printf '\n\033[1;31m%s\033[0m\n' "$1" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "请使用 root 权限运行，例如：sudo opll-update"
  fi
}

load_config() {
  if [[ -f "${CONFIG_FILE}" ]]; then
    # 配置文件由 install.sh 生成，只保存部署路径、服务名和分支，不保存 token。
    # shellcheck disable=SC1090
    source "${CONFIG_FILE}"
  fi
}

run_as_app() {
  runuser -u "${APP_USER}" -- "$@"
}

health_check() {
  curl -fsS "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null
}

wait_for_service() {
  for _ in $(seq 1 30); do
    sleep 1
    if health_check; then
      return 0
    fi
  done
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
  journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
  fail "服务健康检查失败"
}

install_python_dependencies() {
  if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    run_as_app python3 -m venv "${APP_DIR}/.venv"
  fi
  run_as_app "${APP_DIR}/.venv/bin/python" -m pip install --no-cache-dir -r "${APP_DIR}/requirements.txt"
}

main() {
  require_root
  load_config

  if [[ ! -d "${APP_DIR}/.git" ]]; then
    fail "未找到项目仓库：${APP_DIR}"
  fi

  log "检查 GitHub 更新"
  git config --global --add safe.directory "${APP_DIR}" >/dev/null 2>&1 || true
  git -C "${APP_DIR}" fetch origin "${BRANCH}"

  local current_head remote_head
  current_head="$(git -C "${APP_DIR}" rev-parse HEAD)"
  remote_head="$(git -C "${APP_DIR}" rev-parse "origin/${BRANCH}")"

  if [[ "${FORCE}" != "yes" && "${FORCE}" != "1" && "${current_head}" == "${remote_head}" ]]; then
    log "已经是最新版本，无需重启"
    exit 0
  fi

  log "拉取最新代码"
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
  chmod +x "${APP_DIR}/deploy/update.sh" 2>/dev/null || true

  log "更新 Python 依赖"
  install_python_dependencies

  if [[ -n "${APP_ENV_FILE:-}" && -f "${APP_ENV_FILE}" ]] && ! grep -q '^OPENAI_PAY_UI_PROFILE=' "${APP_ENV_FILE}"; then
    printf '%s\n' 'OPENAI_PAY_UI_PROFILE="public"' >>"${APP_ENV_FILE}"
    chmod 600 "${APP_ENV_FILE}"
    log "已补写服务器运行配置：OPENAI_PAY_UI_PROFILE=public（approve 最高 4 路 / 3 轮）"
  fi

  log "重启 OPLL 服务"
  systemctl restart "${SERVICE_NAME}"
  wait_for_service
  systemctl --no-pager --full status "${SERVICE_NAME}" || true

  log "更新完成"
}

main "$@"
