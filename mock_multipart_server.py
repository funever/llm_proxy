"""
车机大模型服务代理 - Multipart 模拟服务

模拟推理服务返回 multipart/form-data 响应：
Part 1: JSON 推理结果
Part 2~N: 图片二进制数据

用于测试代理的 multipart 透传能力。

启动: python mock_multipart_server.py
默认监听 http://127.0.0.1:8012
"""

import os
import json
import time
import uuid
import argparse
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import Response
import uvicorn

parser = argparse.ArgumentParser(description="Multipart模拟推理服务")
parser.add_argument("--port", type=int, default=8012, help="监听端口")
parser.add_argument("--image-dir", type=str, default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "image"), help="图片目录")
args = parser.parse_args()

PORT = args.port
IMAGE_DIR = Path(args.image_dir)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("mock")

app = FastAPI(title="Multipart模拟推理服务")


def build_multipart_response(json_data: dict, images: list):
    """构建 multipart/form-data 响应体"""
    boundary = f"AIProxyBoundary{uuid.uuid4().hex[:12]}"
    parts = []

    # Part 1: JSON 推理结果
    json_str = json.dumps(json_data, ensure_ascii=False)
    part1 = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"text_data\"\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"\r\n"
        f"{json_str}\r\n"
    )
    parts.append(part1.encode("utf-8"))

    # Part 2~N: 图片二进制数据
    for idx, img_info in enumerate(images):
        img_bytes = img_info["data"]
        filename = img_info["filename"]
        width = img_info["width"]
        height = img_info["height"]
        camera_id = img_info.get("camera_id", str(idx))
        timestamp_ns = img_info.get("timestamp_ns", 1780000000000000 + idx * 500000000)
        frame_index = idx

        # 模拟 ARGB 像素数据: 将图片转为 raw bytes
        # 实际推理服务返回的是 ARGB 原始像素, 这里用图片原始二进制模拟
        headers = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"image_{idx}\"; filename=\"{filename}.argb\"\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"X-Camera-Id: {camera_id}\r\n"
            f"X-Timestamp-Ns: {timestamp_ns}\r\n"
            f"X-Frame-Index: {frame_index}\r\n"
            f"X-Image-Width: {width}\r\n"
            f"X-Image-Height: {height}\r\n"
            f"\r\n"
        )
        parts.append(headers.encode("utf-8"))
        parts.append(img_bytes)
        parts.append(b"\r\n")

    # 结束标记
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"

    return body, content_type


def load_images():
    """从 image 目录加载图片并转为 ARGB 原始像素数据"""
    images = []
    if not IMAGE_DIR.exists():
        logger.warning(f"图片目录不存在: {IMAGE_DIR}")
        return images

    try:
        from PIL import Image
        import io
        has_pil = True
    except ImportError:
        has_pil = False
        logger.warning("Pillow not installed, run: pip install Pillow")
        logger.warning("Falling back to raw file bytes (not ARGB pixels)")

    img_files = sorted(IMAGE_DIR.iterdir())
    img_files = [f for f in img_files if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".argb")]

    for img_file in img_files:
        if has_pil:
            # 用 Pillow 读取图片并转为 RGB 3字节像素数据
            # toBitmap() 按 RGB 3字节读取: pixelData[i*3]=R, pixelData[i*3+1]=G, pixelData[i*3+2]=B
            img = Image.open(img_file).convert("RGB")
            width, height = img.size
            rgb_bytes = img.tobytes()  # RGB raw pixels, width*height*3 bytes
            images.append({
                "data": rgb_bytes,
                "filename": img_file.stem,
                "width": width,
                "height": height,
                "camera_id": "0",
                "timestamp_ns": 1780000000000000 + len(images) * 500000000,
            })
            logger.info(f"  loaded: {img_file.name} ({width}x{height}, {len(rgb_bytes)} bytes RGB)")
        else:
            # fallback: 直接发送原始文件字节
            img_bytes = img_file.read_bytes()
            width = 1920
            height = 1080
            images.append({
                "data": img_bytes,
                "filename": img_file.stem,
                "width": width,
                "height": height,
                "camera_id": "0",
                "timestamp_ns": 1780000000000000 + len(images) * 500000000,
            })
            logger.info(f"  loaded: {img_file.name} ({len(img_bytes)} bytes raw, NOT ARGB)")

    return images


@app.post("/chat/completions")
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.body()
    try:
        body_json = json.loads(body)
        model_name = body_json.get("model", "mock-model")
        messages = body_json.get("messages", [])
        user_msg = messages[-1].get("content", "")[:60] if messages else ""
        logger.info(f">>> request: model={model}, msg=\"{user_msg}\"")
    except Exception:
        logger.info(f">>> request: {len(body)} bytes")

    # 构造 JSON 推理结果（与真实 OpenAI ChatCompletionResponse 格式完全一致）
    json_response = {
        "id": "chatcmpl-mock-" + uuid.uuid4().hex[:8],
        "object": "chat.completion",
        "model": model_name,
        "created": int(time.time()),
        "system_fingerprint": None,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "检测到行人靠近，风险等级：中。建议关注周边环境。"
            },
            "finish_reason": "stop",
            "logprobs": None
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "prompt_tokens_details": {"cached_tokens": 0}
        }
    }

    # 加载图片
    images = load_images()
    if images:
        logger.info(f"构建 multipart 响应: 1 JSON part + {len(images)} image parts")
        body_bytes, content_type = build_multipart_response(json_response, images)
        return Response(
            content=body_bytes,
            status_code=200,
            media_type=content_type,
        )
    else:
        logger.info("无图片, 返回纯 JSON 响应")
        return json_response


@app.get("/v1/models")
@app.get("/models")
async def models():
    return {
        "object": "list",
        "data": [
            {"id": "mock-model", "object": "model", "owned_by": "mock"},
        ]
    }


@app.get("/")
async def root():
    images = load_images()
    return {
        "service": "Multipart模拟推理服务",
        "port": PORT,
        "image_dir": str(IMAGE_DIR),
        "images_loaded": len(images),
        "status": "running",
    }


if __name__ == "__main__":
    logger.info(f"模拟推理服务启动: http://127.0.0.1:{PORT}")
    logger.info(f"图片目录: {IMAGE_DIR}")
    images = load_images()
    logger.info(f"已加载 {len(images)} 张图片")
    logger.info(f"如无图片, 请将 .jpg/.png 文件放入 {IMAGE_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)