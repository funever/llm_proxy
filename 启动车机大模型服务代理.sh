#!/bin/bash
# 车机大模型服务代理 - macOS/Linux 启动脚本
#
# 用法:
#   chmod +x 启动车机大模型服务代理.sh
#   ./启动车机大模型服务代理.sh          # 启动 GUI

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "===================================="
echo "  车机大模型服务代理"
echo "===================================="

# check python3
if ! command -v python3 &> /dev/null; then
    echo "[Error] python3 not found, please install it first"
    exit 1
fi

# check tkinter
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "[Error] tkinter not available"
    if [[ "$(uname)" == "Linux" ]]; then
        echo "[Info] on Ubuntu/Debian, run: sudo apt-get install python3-tk"
        echo "[Info] on RHEL/CentOS, run: sudo yum install python3-tkinter"
    elif [[ "$(uname)" == "Darwin" ]]; then
        echo "[Info] on macOS, tkinter should be included with python3 from python.org or brew"
        echo "[Info] if using Homebrew Python: brew install python-tk"
    fi
    exit 1
fi

echo "[Info] starting GUI..."
exec python3 "${SCRIPT_DIR}/proxy_gui.py"