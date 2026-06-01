#!/bin/bash
# 车机大模型服务代理 - Linux 一键启动脚本
#
# 用法:
#   ./start_tunnel.sh                          # 启动代理 + Quick Tunnel
#   ./start_tunnel.sh --tunnel named           # 启动代理 + 命名隧道（固定URL）
#   ./start_tunnel.sh --port 9090              # 自定义代理端口
#   ./start_tunnel.sh --target http://127.0.0.1:11434/v1  # 转发到Ollama
#   ./start_tunnel.sh --no-tunnel              # 仅启动代理，不启动Tunnel
#
# 环境变量（可选）:
#   PROXY_PORT    代理端口，默认 8013
#   TARGET_URL    转发目标，默认 http://127.0.0.1:8012/v1

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "===================================="
echo "  车机大模型服务代理 - Linux"
echo "===================================="

# check python
if ! command -v python3 &> /dev/null; then
    echo "[Error] python3 not found"
    exit 1
fi

# setup virtual environment
VENV_DIR="${SCRIPT_DIR}/venv"
if [ ! -f "${VENV_DIR}/bin/activate" ]; then
    echo "[Info] creating virtual environment..."
    # on Ubuntu/Debian, python3-venv may need to be installed separately
    python3 -m venv "${VENV_DIR}" 2>/dev/null || {
        echo "[Error] python3-venv not available. Install it first:"
        echo "  sudo apt-get update && sudo apt-get install -y python3-venv"
        echo "  # or on RHEL/CentOS: sudo yum install -y python3-venv"
        exit 1
    }
fi
source "${VENV_DIR}/bin/activate"

# ensure pip is available inside venv
if ! command -v pip3 &> /dev/null; then
    echo "[Info] installing pip in venv..."
    python3 -m ensurepip --upgrade
fi

# check and install dependencies
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "[Info] installing dependencies..."
    pip3 install fastapi uvicorn httpx
fi

# check cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo "[Info] installing cloudflared..."
    ARCH="$(uname -m)"
    if [ "${ARCH}" = "x86_64" ]; then
        CLOUDFLARED_ARCH="amd64"
    elif [ "${ARCH}" = "aarch64" ] || [ "${ARCH}" = "arm64" ]; then
        CLOUDFLARED_ARCH="arm64"
    else
        echo "[Error] unsupported architecture: ${ARCH}"
        exit 1
    fi

    if [ -f /etc/debian_version ]; then
        curl -L --output /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CLOUDFLARED_ARCH}.deb"
        sudo dpkg -i /tmp/cloudflared.deb
        rm -f /tmp/cloudflared.deb
    elif [ -f /etc/redhat-release ]; then
        curl -L --output /tmp/cloudflared.rpm "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CLOUDFLARED_ARCH}.rpm"
        sudo rpm -i /tmp/cloudflared.rpm
        rm -f /tmp/cloudflared.rpm
    elif [[ "$(uname)" == "Darwin" ]]; then
        if command -v brew &> /dev/null; then
            brew install cloudflared
        else
            echo "[Error] Homebrew not found. Install cloudflared manually:"
            echo "  https://developers.cloudflare.com/cloudflare-one/connections/network-apps/cli-tool/"
            exit 1
        fi
    else
        echo "[Error] unsupported OS, please install cloudflared manually:"
        echo "  https://developers.cloudflare.com/cloudflare-one/connections/network-apps/cli-tool/"
        exit 1
    fi
    echo "[Info] cloudflared installed"
fi

# default args: start with quick tunnel
PYTHON="${VENV_DIR}/bin/python3"
if [[ "$*" != *"--tunnel"* ]] && [[ "$*" != *"--no-tunnel"* ]]; then
    exec "${PYTHON}" "${SCRIPT_DIR}/linux_proxy.py" --tunnel "$@"
else
    exec "${PYTHON}" "${SCRIPT_DIR}/linux_proxy.py" "$@"
fi