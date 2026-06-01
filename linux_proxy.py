"""
车机大模型服务代理 - Linux 版

功能：
- 监听本地端口，接收 OpenAI 协议请求
- 转发到本地大模型服务（如 vLLM/Ollama）
- 记录完整请求和响应日志到文件
- 自动启动 Cloudflare Quick Tunnel 穿透到公网
- 支持命名隧道（固定 URL）

使用方法：
1. pip install fastapi uvicorn httpx
2. python linux_proxy.py --tunnel          # 启动代理 + Quick Tunnel
3. python linux_proxy.py --tunnel named    # 启动代理 + 命名隧道（固定URL）
4. python linux_proxy.py                   # 仅启动代理，不启动 Tunnel

命令行参数：
  --port PORT         代理监听端口，默认 8013
  --target URL        目标大模型服务地址，默认 http://127.0.0.1:8012/v1
  --tunnel [named]    启动 Cloudflare Tunnel（named 表示命名隧道，固定URL）
  --log-dir DIR       日志目录，默认 ./logs
"""

import os
import sys
import json
import time
import re
import logging
import subprocess
import signal
import argparse
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import uvicorn

# parse args
parser = argparse.ArgumentParser(description="车机大模型服务代理")
parser.add_argument("--port", type=int, default=int(os.environ.get("PROXY_PORT", "8013")), help="代理监听端口")
parser.add_argument("--target", type=str, default=os.environ.get("TARGET_URL", "http://127.0.0.1:8012/v1"), help="目标大模型服务地址")
parser.add_argument("--tunnel", nargs="?", const="quick", default=None, help="启动 Tunnel: 'quick' 或 'named'")
parser.add_argument("--log-dir", type=str, default=os.environ.get("LOG_DIR", "./logs"), help="日志目录")
args = parser.parse_args()

PROXY_PORT = args.port
TARGET_URL = args.target
LOG_DIR = args.log_dir
TUNNEL_MODE = args.tunnel

app = FastAPI(title="车机大模型服务代理")

# ensure log dir exists
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# setup file logger
log_file = Path(LOG_DIR) / f"proxy_{time.strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("proxy")

# global variable to store tunnel public URL
tunnel_public_url = ""


def strip_path_overlap(target_url, request_path):
    """Strip common suffix overlap between target URL and request path.
    e.g. target_url ends with /v1, request_path is /v1/chat/completions
    -> should become target_url + /chat/completions
    """
    url_path_part = target_url.rstrip("/").rsplit("/", 1)[-1] if "/" in target_url.rstrip("//").split("//")[-1] else ""
    base_suffix = "/" + url_path_part if url_path_part else ""
    if base_suffix and base_suffix != "/" and request_path.startswith(base_suffix + "/"):
        return target_url.rstrip("/") + request_path[len(base_suffix):]
    elif base_suffix and base_suffix != "/" and request_path == base_suffix:
        return target_url.rstrip("/")
    else:
        return target_url.rstrip("/") + request_path


def format_json(data):
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            obj = json.loads(data)
            return json.dumps(obj, indent=2, ensure_ascii=False)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return str(data)


async def forward_request(request: Request):
    path = request.url.path
    method = request.method
    target = strip_path_overlap(TARGET_URL, path)

    # read request body
    body = await request.body()
    body_text = body.decode("utf-8", errors="replace") if body else ""

    # forward headers (skip hop-by-hop headers)
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() not in ("host", "transfer-encoding", "connection", "content-length"):
            forward_headers[key] = value
    forward_headers["host"] = TARGET_URL.split("/")[2].split(":")[0]

    # log request
    logger.info("=" * 60)
    logger.info(f">>> {method} {path} -> {target}")
    logger.info("[Request Headers]")
    for k, v in request.headers.items():
        logger.info(f"  {k}: {v}")
    if body_text:
        logger.info("[Request Body]")
        logger.info(format_json(body_text))

    # check if streaming request
    is_stream = False
    if body_text:
        try:
            body_json = json.loads(body_text)
            is_stream = body_json.get("stream", False)
        except Exception:
            pass

    try:
        if is_stream:
            # streaming response
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                async with client.stream(method, target, content=body, headers=forward_headers) as resp:
                    logger.info(f"<<< {resp.status_code} (streaming)")
                    logger.info("[Response Headers]")
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "connection"):
                            logger.info(f"  {k}: {v}")

                    async def stream_generator():
                        chunk_count = 0
                        collected = ""
                        try:
                            async for chunk in resp.aiter_bytes():
                                chunk_count += 1
                                chunk_text = chunk.decode("utf-8", errors="replace")
                                collected += chunk_text
                                yield chunk
                        finally:
                            logger.info(f"[Streaming] {chunk_count} chunks sent")

                    response_headers = {}
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                            response_headers[k] = v

                    return StreamingResponse(
                        stream_generator(),
                        status_code=resp.status_code,
                        headers=response_headers,
                        media_type=resp.headers.get("content-type", "text/event-stream"),
                    )

        else:
            # non-streaming request
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.request(method, target, content=body, headers=forward_headers)

            resp_body = resp.text
            logger.info(f"<<< {resp.status_code}")
            logger.info("[Response Headers]")
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    logger.info(f"  {k}: {v}")
            logger.info("[Response Body]")
            logger.info(format_json(resp_body))

            response_headers = {}
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                    response_headers[k] = v

            try:
                resp_json = json.loads(resp_body) if resp_body else {}
            except Exception:
                resp_json = {"raw": resp_body}

            return JSONResponse(
                content=resp_json,
                status_code=resp.status_code,
                headers=response_headers,
            )

    except httpx.ConnectError as e:
        logger.error(f"[Error] cannot connect to target: {e}")
        return JSONResponse(content={"error": f"cannot connect to {TARGET_URL}: {e}"}, status_code=502)
    except httpx.TimeoutException as e:
        logger.error(f"[Error] timeout: {e}")
        return JSONResponse(content={"error": f"timeout: {e}"}, status_code=504)
    except Exception as e:
        logger.error(f"[Error] {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


# catch all paths
@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
async def catch_all(request: Request, path: str):
    return await forward_request(request)


@app.get("/")
async def root():
    return {
        "service": "车机大模型服务代理",
        "target": TARGET_URL,
        "proxy_port": PROXY_PORT,
        "tunnel_url": tunnel_public_url,
        "status": "running",
    }


def start_tunnel(proxy_port, mode="quick"):
    """Start Cloudflare Tunnel and return public URL."""
    global tunnel_public_url

    cloudflared = os.environ.get("CLOUDFLARED_PATH", "cloudflared")

    if mode == "named":
        cmd = [cloudflared, "tunnel", "run", "llm-proxy"]
        logger.info(f"[Tunnel] starting named tunnel 'llm-proxy'...")
    else:
        cmd = [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{proxy_port}"]
        logger.info(f"[Tunnel] starting quick tunnel...")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )

    # read cloudflared output to find public URL
    url_found = False
    timeout = 30
    start_time = time.time()

    while not url_found and time.time() - start_time < timeout:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                logger.error("[Tunnel] cloudflared exited unexpectedly")
                return None
            continue

        line = line.strip()
        if line:
            logger.info(f"[Tunnel] {line}")

        # extract URL from output
        urls = re.findall(r'https://[a-zA-Z0-9\-]+\.(?:trycloudflare|cfargotunnel)\.com[^\s|]*', line)
        if urls:
            tunnel_public_url = urls[0]
            url_found = True
            logger.info("=" * 60)
            logger.info(f"[Tunnel] public URL: {tunnel_public_url}")
            logger.info(f"[Tunnel] car device base_url: {tunnel_public_url}/v1")
            logger.info("=" * 60)

    if not url_found:
        logger.warning("[Tunnel] could not detect public URL within 30 seconds")
        logger.warning("[Tunnel] check the log output above for the URL")

    return process


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info(f"代理服务启动: http://0.0.0.0:{PROXY_PORT}")
    logger.info(f"转发目标: {TARGET_URL}")
    logger.info(f"日志目录: {LOG_DIR}")
    logger.info("=" * 60)

    tunnel_process = None
    if TUNNEL_MODE:
        tunnel_process = start_tunnel(PROXY_PORT, TUNNEL_MODE)

    def shutdown(signum, frame):
        logger.info("[Shutdown] stopping services...")
        if tunnel_process:
            tunnel_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    uvicorn.run(app, host="0.0.0.0", port=PROXY_PORT)