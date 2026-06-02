# 车机大模型服务代理

让车机（Android）访问大模型服务的本地代理工具。支持两种连接模式，兼容 multipart 响应透传。

## 架构

**ADB Reverse 模式（车机通过 USB 连接电脑）：**

```
车机 → adb reverse → 电脑代理(18900) → 大模型服务
```

**Cloudflare Tunnel 模式（车机通过公网访问，无需 USB）：**

```
车机 → https://xxx.trycloudflare.com → Cloudflare → 电脑代理(8013) → 大模型服务
```

## 文件说明

| 文件 | 平台 | 说明 |
|------|------|------|
| `proxy_gui.py` | Windows / macOS / Linux | GUI 主程序，支持 ADB Reverse 和 Cloudflare Tunnel 两种模式 |
| `linux_proxy.py` | macOS / Linux | 命令行版代理服务，支持 `--tunnel`/`--port`/`--target` 参数 |
| `start_tunnel.sh` | macOS / Linux | 一键启动脚本，自动创建 venv、安装依赖和 cloudflared |
| `test_llm_proxy.sh` | Android (adb shell) | 测试脚本，base_url 作为参数，自动识别 https 加 `-k` |
| `mock_multipart_server.py` | 全平台 | 模拟推理服务，返回 JSON + RGB 图片的 multipart 响应，用于联调测试 |
| `启动车机大模型服务代理.bat` | Windows | 双击启动 GUI |
| `启动车机大模型服务代理.sh` | macOS / Linux | 启动 GUI，自动检查 python3 和 tkinter |
| `image/` | - | mock 服务用的测试图片目录 |

## 快速开始

### Windows

双击 `启动车机大模型服务代理.bat`，或命令行运行：

```bash
python proxy_gui.py
```

### macOS / Linux

```bash
chmod +x 启动车机大模型服务代理.sh
./启动车机大模型服务代理.sh
```

### Linux 命令行（无 GUI）

```bash
# 启动代理 + Quick Tunnel
python3 linux_proxy.py --tunnel

# 自定义端口和目标
python3 linux_proxy.py --port 9090 --target http://127.0.0.1:11434/v1 --tunnel

# 仅启动代理，不启动 Tunnel
python3 linux_proxy.py

# 一键脚本（自动安装依赖）
./start_tunnel.sh
```

## GUI 使用说明

### 目标大模型服务

界面顶部的 Base URL 是代理转发的目标地址，默认为远端百炼服务。点击 **Edit** 可修改，点击 **Lock** 保存生效。

常见目标地址：

| 服务 | Base URL |
|------|----------|
| 内部大模型推理服务 | `https://your-internal-llm-service.example.com/v1` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` |
| 本地 vLLM | `http://127.0.0.1:8012/v1` |
| Mock 服务 | `http://127.0.0.1:8012/v1` |

### ADB Reverse 模式

适用于车机通过 USB 连接电脑的场景。

1. 车机通过 USB 连接电脑，确保 `adb devices` 能看到设备
2. 点击 **Start Proxy** 启动代理
3. 点击 **ADB Reverse** 设置端口映射
4. 车机访问 `http://localhost:8900/v1`

### Cloudflare Tunnel 模式

适用于车机无法 USB 连接电脑、但能访问公网的场景。

1. 安装 cloudflared（Windows 放到同目录，macOS 用 `brew install cloudflared`，Linux 脚本自动安装）
2. 点击 **Start Tunnel**
3. 界面显示公网地址（如 `https://xxx-yyy.trycloudflare.com`）
4. 车机访问该地址（需加 `-k` 或代码中跳过 SSL 校验）

**注意：** Quick Tunnel 每次重启 URL 会变化。固定 URL 需要域名 + 命名隧道。

## 车机端测试

将测试脚本推送到车机执行：

```bash
# ADB 模式
adb shell "curl -s http://localhost:8900/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{\"model\":\"bailian/glm-5\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}'"

# Tunnel 模式（需加 -k 跳过 SSL）
adb shell "curl -k -s https://xxx.trycloudflare.com/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{\"model\":\"bailian/glm-5\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}'"
```

或使用测试脚本（base_url 作为参数）：

```bash
adb push test_llm_proxy.sh /data/local/tmp/
adb shell "sh /data/local/tmp/test_llm_proxy.sh http://localhost:8900"
adb shell "sh /data/local/tmp/test_llm_proxy.sh https://xxx.trycloudflare.com"
```

## Multipart 响应透传

代理支持推理服务返回 `multipart/form-data` 响应（Part 1 为 JSON 推理结果，Part 2~N 为图片二进制数据），原样透传到车机。

### 使用 Mock 服务联调

1. 将测试图片放入 `image/` 目录
2. 启动 Mock 服务：

```bash
pip install Pillow  # 首次需要安装
python mock_multipart_server.py
```

3. 修改代理 Base URL 为 `http://127.0.0.1:8012/v1`
4. 车机发起请求，将收到 multipart 响应

### Mock 服务返回格式

```
HTTP/1.1 200 OK
Content-Type: multipart/form-data; boundary=AIProxyBoundaryxxx

--AIProxyBoundaryxxx
Content-Disposition: form-data; name="text_data"
Content-Type: application/json; charset=UTF-8

{"id":"chatcmpl-xxx","choices":[{"message":{"content":"检测到行人靠近..."}}]}

--AIProxyBoundaryxxx
Content-Disposition: form-data; name="image_0"; filename="1.argb"
Content-Type: application/octet-stream
X-Camera-Id: 0
X-Timestamp-Ns: 1780000000000000
X-Frame-Index: 0
X-Image-Width: 2048
X-Image-Height: 2048

<RGB 3字节像素数据>

--AIProxyBoundaryxxx--
```

## 两种模式对比

| | ADB Reverse | Cloudflare Tunnel |
|---|---|---|
| 连接方式 | USB | 公网 |
| 车机地址 | `http://localhost:8900` | `https://xxx.trycloudflare.com` |
| 需要 VPN | 否 | 车机需能访问公网 |
| SSL 问题 | 无 | 车机时间不准需跳过校验 |
| URL 固定 | 是 | Quick Tunnel 每次变化 |
| 延迟 | 低（USB） | 较高（经 Cloudflare） |
| 适用场景 | 开发调试 | 远程部署 |

## 车机端注意事项

- 车机系统时间不准会导致 SSL 证书校验失败，代码中需设置 `verify=False` 或 `trustAllCertificates=true`
- 车机 DNS 可能无法解析 `trycloudflare.com`，需确认车机网络能访问该域名
- ADB Reverse 在设备重启后失效，需重新执行
