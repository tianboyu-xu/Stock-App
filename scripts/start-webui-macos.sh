#!/bin/bash
# macOS 一键启动 WebUI（双击 Start-WebUI.command 即可）
#
# 行为与 Windows 的 scripts/start-local.ps1 对齐：
#   1. 自动定位仓库根目录（不写死绝对路径）
#   2. 查找 Python 3.10+，缺失则提示用 Homebrew 安装
#   3. 自动创建 .venv 并安装 requirements.txt（缺失时）
#   4. 缺失 .env 时从 .env.example 复制
#   5. 前台启动 `python main.py --serve-only`，日志可见，Ctrl+C 停止
#   6. 服务就绪后自动用默认浏览器打开 WebUI
#
# 端口/地址不写死：优先使用环境变量 WEBUI_HOST / WEBUI_PORT，
# 其次读取仓库 .env 中的同名配置，最后回退到 127.0.0.1:8000。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

DEFAULT_HOST="127.0.0.1"
DEFAULT_PORT="8000"

# 地址/端口解析用的配置文件：.env 优先，缺失时回退到 .env.example，
# 以便首次运行也能读到正确端口；真正的 .env 复制放在 Python 检查之后，
# 确保环境不满足时不触碰用户文件。
CONFIG_FILE="$REPO_ROOT/.env"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="$REPO_ROOT/.env.example"

# 从配置文件中读取单个键（忽略注释与前后引号），环境变量优先。
read_dotenv_value() {
  local key="$1" env_file="$CONFIG_FILE" line value
  if [ ! -f "$env_file" ]; then
    return 0
  fi
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$env_file" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return 0
  fi
  value="${line#*=}"
  # 去掉行尾注释并裁剪空白与首尾引号
  value="$(printf '%s' "$value" | sed -e 's/[[:space:]]*#[^"]*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")"
  printf '%s' "$value"
}

BIND_HOST="${WEBUI_HOST:-$(read_dotenv_value WEBUI_HOST || true)}"
BIND_PORT="${WEBUI_PORT:-$(read_dotenv_value WEBUI_PORT || true)}"
[ -n "$BIND_HOST" ] || BIND_HOST="$DEFAULT_HOST"
[ -n "$BIND_PORT" ] || BIND_PORT="$DEFAULT_PORT"

# 0.0.0.0 / :: 等公网监听地址只用于服务端绑定，浏览器仍走本机回环打开。
BROWSER_HOST="$BIND_HOST"
case "$BROWSER_HOST" in
  0.0.0.0|"::"|"*") BROWSER_HOST="127.0.0.1" ;;
esac
WEBUI_URL="http://${BROWSER_HOST}:${BIND_PORT}"

is_python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  local cand
  for cand in "$REPO_ROOT/.venv/bin/python" python3.14 python3.13 python3.12 python3.11 python3.10 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1 && is_python_ok "$cand"; then
      command -v "$cand" 2>/dev/null || printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
  echo "错误：未找到 Python 3.10+。macOS 自带的 Python 3.9 版本过旧，无法运行本项目。" >&2
  echo "" >&2
  echo "请先安装 Homebrew 版 Python（任选其一），然后重新双击启动：" >&2
  echo "  brew install python@3.12" >&2
  echo "  brew install python@3.13" >&2
  echo "" >&2
  echo "安装完成后重新双击 Start-WebUI.command 即可。" >&2
  exit 1
fi
echo "使用 Python: $PYTHON ($("$PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'))"

# Python 就绪后才落盘用户文件：缺失 .env 时从模板复制。
if [ ! -f "$REPO_ROOT/.env" ]; then
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  echo "已从 .env.example 创建 .env（请按需填入模型 Key 与自选股）。"
fi

# 虚拟环境：缺失则创建；已存在但版本过旧则提示重建（不静默删除用户环境）。
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
FRESH_VENV=0
if [ ! -x "$VENV_PYTHON" ]; then
  echo "创建虚拟环境 .venv ..."
  "$PYTHON" -m venv "$REPO_ROOT/.venv"
  FRESH_VENV=1
elif ! is_python_ok "$VENV_PYTHON"; then
  echo "错误：现有 .venv 的 Python 版本过旧（需要 3.10+）。" >&2
  echo "请执行以下命令重建后再启动：" >&2
  echo "  rm -rf .venv && brew install python@3.12" >&2
  exit 1
fi

# 依赖：全新虚拟环境必装；旧环境仅在 fastapi/uvicorn 缺失时补装。
if [ "$FRESH_VENV" -eq 1 ]; then
  echo "安装依赖 requirements.txt（首次较慢，请稍候）..."
  "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"
elif ! "$VENV_PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "检测到依赖缺失，正在补装 requirements.txt ..."
  "$VENV_PYTHON" -m pip install -r "$REPO_ROOT/requirements.txt"
fi

# 前端提示：后端 WEBUI_AUTO_BUILD=true 时会自动构建；此处仅在 npm 缺失
# 且静态产物缺失时提前给出可操作的中文提示，不阻断后端启动。
if ! command -v npm >/dev/null 2>&1; then
  if [ ! -f "$REPO_ROOT/static/index.html" ] || [ -z "$(ls "$REPO_ROOT/static/assets/"*.js 2>/dev/null || true)" ]; then
    echo "提示：未检测到 npm，且 static/ 前端产物缺失，WebUI 首页将显示 Frontend Not Built 引导页，API 仍可用。"
    echo "如需完整界面，请执行 brew install node，然后运行：cd apps/dsa-web && npm ci && npm run build"
  fi
fi

echo "正在启动 WebUI: ${WEBUI_URL}（日志保留在当前窗口，Ctrl+C 停止；服务就绪后将自动打开浏览器）"

# 服务就绪后自动打开浏览器：轮询跟随主进程生命周期（覆盖首次 pip/npm 构建的长等待，
# 最长 30 分钟）；主进程退出时由 EXIT trap 回收轮询任务，不会残留。
(
  for _ in $(seq 1 900); do
    kill -0 $$ 2>/dev/null || exit 0
    if curl -fsS -m 2 "${WEBUI_URL}/api/health" >/dev/null 2>&1; then
      open "$WEBUI_URL"
      exit 0
    fi
    sleep 2
  done
  echo "等待 WebUI 超时（30 分钟），请手动打开 $WEBUI_URL" >&2
) &
OPENER_PID=$!
trap 'kill $OPENER_PID 2>/dev/null || true' EXIT INT TERM

"$VENV_PYTHON" main.py --serve-only --host "$BIND_HOST" --port "$BIND_PORT"
EXIT_CODE=$?

kill "$OPENER_PID" 2>/dev/null || true
trap - EXIT INT TERM
exit "$EXIT_CODE"
