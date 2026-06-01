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

# check and install dependencies
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "[Info] installing dependencies..."
    pip3 install fastapi uvicorn httpx
fi

# check cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo "[Info] installing cloudflared..."
    if [ -f /etc/debian_version ]; then
        curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
        sudo dpkg -i /tmp/cloudflared.deb
        rm -f /tmp/cloudflared.deb
    elif [ -f /etc/redhat-release ]; then
        curl -L --output /tmp/cloudflared.rpm https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.rpm
        sudo rpm -i /tmp/cloudflared.rpm
        rm -f /tmp/cloudflared.rpm
    else
        echo "[Error] unsupported OS, please install cloudflared manually:"
        echo "  https://developers.cloudflare.com/cloudflare-one/connections/network-apps/cli-tool/"
        exit 1
    fi
    echo "[Info] cloudflared installed"
fi

# default args: start with quick tunnel
if [[ "$*" != *"--tunnel"* ]] && [[ "$*" != *"--no-tunnel"* ]]; then
    exec python3 "${SCRIPT_DIR}/linux_proxy.py" --tunnel "$@"
else
    exec python3 "${SCRIPT_DIR}/linux_proxy.py" "$@"
fi