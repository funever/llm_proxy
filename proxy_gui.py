"""
车机大模型服务代理 - Windows GUI 版

功能：
1. ADB Reverse 模式：通过 USB + adb reverse 让车机访问代理
2. Cloudflare Tunnel 模式：通过公网穿透让车机访问代理
3. 可编辑的 Base URL（目标大模型服务地址）
4. 完整的请求/响应日志显示（含横向滚动条）
"""

import tkinter as tk
from tkinter import ttk
import threading
import http.client
import http.server
import socketserver
import json
import ssl
import subprocess
import shutil
import urllib.parse
import time
import os
import logging
from pathlib import Path
from collections import deque

# defaults
DEFAULT_BASE_URL = "https://codingxrui.geely-test.com/bailian/openai/v1"
DEFAULT_PROXY_PORT = "18900"
DEFAULT_DEVICE_PORT = "8900"
DEFAULT_TUNNEL_PORT = "8013"

EXTRA_HEADERS = {
    "x-api-key": "sk_ind_test_biqzzhj9hmtnwpodd5",
    "anthropic-version": "2023-06-01",
    "Authorization": "Bearer sk_ind_test_biqzzhj9hmtnwpodd5",
}

SSL_CONTEXT = ssl.create_default_context()
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# file logger
log_file = LOG_DIR / f"proxy_{time.strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
)
file_logger = logging.getLogger("proxy_file")

# gui log buffer
log_buffer = deque(maxlen=2000)


def add_log(msg):
    log_buffer.append(msg)
    file_logger.info(msg)


def format_json(data):
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            obj = json.loads(data)
            return json.dumps(obj, indent=2, ensure_ascii=False)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    MAX_REDIRECTS = 5
    target_base_url = DEFAULT_BASE_URL
    extra_headers = EXTRA_HEADERS

    def do_request(self):
        path = self.path
        # strip common suffix overlap between target base url and request path
        # e.g. base_url ends with /v1, request path is /v1/chat/completions
        # -> should become base_url + /chat/completions, not base_url + /v1/chat/completions
        base_suffix = "/" + self.target_base_url.rstrip("/").rsplit("/", 1)[-1] if "/" in self.target_base_url.rstrip("//").split("//")[-1] else ""
        if base_suffix and base_suffix != "/" and path.startswith(base_suffix + "/"):
            target_url = self.target_base_url.rstrip("/") + path[len(base_suffix):]
        elif base_suffix and base_suffix != "/" and path == base_suffix:
            target_url = self.target_base_url.rstrip("/")
        else:
            target_url = self.target_base_url.rstrip("/") + path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        if body and self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers.get("Content-Type")

        add_log("=" * 60)
        add_log(f">>> {self.command} {path}")
        add_log("[Request Headers]")
        for k, v in self.headers.items():
            add_log(f"  {k}: {v}")
        if body:
            add_log("[Request Body]")
            add_log(format_json(body))

        try:
            # determine if target is http or https
            is_https = target_url.startswith("https")

            for _ in range(self.MAX_REDIRECTS):
                parsed = urllib.parse.urlparse(target_url)
                host = parsed.hostname
                port = parsed.port or (443 if is_https else 80)
                req_path = parsed.path
                if parsed.query:
                    req_path += "?" + parsed.query

                if is_https:
                    conn = http.client.HTTPSConnection(host, port, context=SSL_CONTEXT, timeout=120)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=120)

                conn.request(self.command, req_path, body=body, headers=headers)
                resp = conn.getresponse()

                if resp.status in (301, 302, 307, 308):
                    location = resp.getheader("location", "")
                    resp.read()
                    conn.close()
                    add_log(f"[Redirect] {resp.status} -> {location}")
                    if not location:
                        break
                    target_url = urllib.parse.urljoin(target_url, location)
                    is_https = target_url.startswith("https")
                    continue

                resp_body = resp.read()
                resp_content_type = resp.getheader("Content-Type", "")

                add_log(f"<<< {resp.status} {resp.reason}")
                add_log("[Response Headers]")
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        add_log(f"  {k}: {v}")

                # log response body: multipart as size summary, others as formatted
                if "multipart/" in resp_content_type:
                    add_log(f"[Response Body] multipart, {len(resp_body)} bytes (raw binary, not logged)")
                else:
                    add_log("[Response Body]")
                    add_log(format_json(resp_body))

                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, val)
                self.end_headers()
                self.wfile.write(resp_body)
                conn.close()
                return

            add_log(f"[Error] redirect limit reached, url={target_url}")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "too many redirects"}).encode())
        except Exception as e:
            add_log(f"[Error] {e}")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        self.do_request()

    def do_POST(self):
        self.do_request()

    def do_DELETE(self):
        self.do_request()

    def log_message(self, format, *args):
        pass


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class LLMProxyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("车机大模型服务代理")
        self.root.geometry("960x640")
        self.root.resizable(True, True)

        self.server = None
        self.server_thread = None
        self.proxy_running = False

        self.tunnel_server = None
        self.tunnel_server_thread = None
        self.tunnel_proxy_running = False
        self.tunnel_process = None
        self.tunnel_running = False

        self._build_ui()
        self._refresh_logs()

    def _build_ui(self):
        # === Base URL row ===
        url_frame = ttk.LabelFrame(self.root, text="目标大模型服务", padding=8)
        url_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.url_var = tk.StringVar(value=DEFAULT_BASE_URL)
        self.url_entry = tk.Entry(url_frame, textvariable=self.url_var, font=("Consolas", 9), state="disabled")
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.url_edit_btn = ttk.Button(url_frame, text="Edit", width=6, command=self._toggle_url_edit)
        self.url_edit_btn.pack(side=tk.LEFT)

        # === Mode row ===
        mode_frame = ttk.LabelFrame(self.root, text="连接模式", padding=8)
        mode_frame.pack(fill=tk.X, padx=8, pady=4)

        # ADB mode
        adb_frame = ttk.Frame(mode_frame)
        adb_frame.pack(fill=tk.X)

        ttk.Label(adb_frame, text="ADB Reverse 模式：").pack(side=tk.LEFT)
        ttk.Label(adb_frame, text="Proxy Port:").pack(side=tk.LEFT, padx=(8, 4))
        self.proxy_port_var = tk.StringVar(value=DEFAULT_PROXY_PORT)
        ttk.Entry(adb_frame, textvariable=self.proxy_port_var, width=6).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(adb_frame, text="Device Port:").pack(side=tk.LEFT, padx=(0, 4))
        self.device_port_var = tk.StringVar(value=DEFAULT_DEVICE_PORT)
        ttk.Entry(adb_frame, textvariable=self.device_port_var, width=6).pack(side=tk.LEFT, padx=(0, 8))

        self.start_btn = ttk.Button(adb_frame, text="Start Proxy", command=self._toggle_proxy)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.reverse_btn = ttk.Button(adb_frame, text="ADB Reverse", command=self._do_adb_reverse)
        self.reverse_btn.pack(side=tk.LEFT)

        # Tunnel mode
        tunnel_frame = ttk.Frame(mode_frame)
        tunnel_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(tunnel_frame, text="Cloudflare Tunnel 模式：").pack(side=tk.LEFT)
        ttk.Label(tunnel_frame, text="Tunnel Port:").pack(side=tk.LEFT, padx=(8, 4))
        self.tunnel_port_var = tk.StringVar(value=DEFAULT_TUNNEL_PORT)
        ttk.Entry(tunnel_frame, textvariable=self.tunnel_port_var, width=6).pack(side=tk.LEFT, padx=(0, 8))

        self.tunnel_btn = ttk.Button(tunnel_frame, text="Start Tunnel", command=self._toggle_tunnel)
        self.tunnel_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.tunnel_url_var = tk.StringVar(value="")
        ttk.Label(tunnel_frame, text="公网地址:").pack(side=tk.LEFT, padx=(0, 4))
        self.tunnel_url_entry = ttk.Entry(tunnel_frame, textvariable=self.tunnel_url_var, width=45)
        self.tunnel_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.tunnel_url_entry.config(state="readonly")

        # === Status bar ===
        status = ttk.Frame(self.root, padding=(8, 2))
        status.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="Proxy: stopped | Tunnel: stopped")
        ttk.Label(status, textvariable=self.status_var, foreground="gray").pack(side=tk.LEFT)

        # === Log area ===
        log_frame = ttk.LabelFrame(self.root, text="请求/响应日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        log_scroll_y = ttk.Scrollbar(log_frame, orient=tk.VERTICAL)
        log_scroll_x = ttk.Scrollbar(log_frame, orient=tk.HORIZONTAL)
        self.log_text = tk.Text(
            log_frame, wrap=tk.NONE, font=("Consolas", 9),
            yscrollcommand=log_scroll_y.set, xscrollcommand=log_scroll_x.set
        )
        log_scroll_y.config(command=self.log_text.yview)
        log_scroll_x.config(command=self.log_text.xview)

        log_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        log_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        # clear button inside log frame
        clear_btn = ttk.Button(log_frame, text="Clear Log", command=self._clear_log)
        clear_btn.place(relx=1.0, rely=0.0, x=-70, y=2)

    def _toggle_url_edit(self):
        current_state = str(self.url_entry.cget("state"))
        if current_state in ("disabled", "readonly"):
            self.url_entry.config(state="normal")
            self.url_edit_btn.config(text="Lock")
        else:
            self.url_entry.config(state="disabled")
            self.url_edit_btn.config(text="Edit")
            ProxyHandler.target_base_url = self.url_var.get()

    def _toggle_proxy(self):
        if self.proxy_running:
            self._stop_proxy()
        else:
            self._start_proxy()

    def _start_proxy(self):
        port = int(self.proxy_port_var.get())
        ProxyHandler.target_base_url = self.url_var.get()

        try:
            self.server = ReusableTCPServer(("127.0.0.1", port), ProxyHandler)
        except Exception as e:
            add_log(f"[Proxy] failed to start: {e}")
            return

        self.proxy_running = True
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

        add_log(f"[Proxy] started on http://127.0.0.1:{port}")
        add_log(f"[Proxy] forwarding to {ProxyHandler.target_base_url}")
        self.start_btn.config(text="Stop Proxy")
        self._update_status()

    def _stop_proxy(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.proxy_running = False
        add_log("[Proxy] stopped")
        self.start_btn.config(text="Start Proxy")
        self._update_status()

    def _do_adb_reverse(self):
        device_port = int(self.device_port_var.get())
        proxy_port = int(self.proxy_port_var.get())
        adb = shutil.which("adb")

        if not adb:
            add_log("[ADB] adb not found in PATH")
            return

        def run():
            try:
                subprocess.run(
                    [adb, "reverse", f"tcp:{device_port}", f"tcp:{proxy_port}"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
                )
                add_log(f"[ADB] reverse set: device tcp:{device_port} -> pc tcp:{proxy_port}")

                result = subprocess.run(
                    [adb, "devices"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5
                )
                lines = result.stdout.strip().splitlines()
                for line in lines[1:]:
                    if line.strip() and "device" in line and not line.startswith("*"):
                        serial = line.split()[0]
                        add_log(f"[ADB] device: {serial}")
            except Exception as e:
                add_log(f"[ADB] error: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _toggle_tunnel(self):
        if self.tunnel_running:
            self._stop_tunnel()
        else:
            self._start_tunnel()

    def _start_tunnel(self):
        # start a separate proxy on tunnel port (independent from ADB proxy)
        tunnel_port = int(self.tunnel_port_var.get())
        ProxyHandler.target_base_url = self.url_var.get()

        if self.tunnel_proxy_running:
            add_log("[Tunnel] tunnel proxy already running")
        else:
            try:
                self.tunnel_server = ReusableTCPServer(("127.0.0.1", tunnel_port), ProxyHandler)
                self.tunnel_proxy_running = True
                self.tunnel_server_thread = threading.Thread(target=self.tunnel_server.serve_forever, daemon=True)
                self.tunnel_server_thread.start()
                add_log(f"[Tunnel] proxy started on http://127.0.0.1:{tunnel_port}")
            except Exception as e:
                add_log(f"[Tunnel] failed to start proxy on port {tunnel_port}: {e}")
                return

        # check cloudflared: first from app directory, then from PATH
        app_dir = os.path.dirname(os.path.abspath(__file__))
        # Windows: cloudflared.exe, macOS/Linux: cloudflared
        local_candidates = [
            os.path.join(app_dir, "cloudflared"),
            os.path.join(app_dir, "cloudflared.exe"),
        ]
        cloudflared = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
        for candidate in local_candidates:
            if os.path.isfile(candidate):
                cloudflared = candidate
                break
        if not cloudflared:
            add_log("[Tunnel] cloudflared not found")
            add_log("[Tunnel] please download cloudflared from:")
            add_log("[Tunnel]   https://github.com/cloudflare/cloudflared/releases/latest")
            add_log(f"[Tunnel] and put it in: {app_dir}")
            return

        add_log("[Tunnel] starting Cloudflare Quick Tunnel...")
        self.tunnel_btn.config(text="Stop Tunnel")

        # monitor cloudflared output for the public URL
        self._tunnel_url_found = False

        def run_tunnel():
            try:
                process = subprocess.Popen(
                    [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{tunnel_port}"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding="utf-8", errors="replace"
                )
                self.tunnel_process = process
                self.tunnel_running = True
                self._update_status()

                for line in process.stdout:
                    line = line.strip()
                    if line:
                        add_log(f"[Tunnel] {line}")
                    # detect public URL in cloudflared output
                    if "https://" in line and not self._tunnel_url_found:
                        # extract URL (trycloudflare.com or cfargotunnel.com)
                        import re
                        urls = re.findall(r'https://[a-zA-Z0-9\-]+\.(?:trycloudflare|cfargotunnel)\.com[^\s|]*', line)
                        if urls:
                            self._tunnel_url_found = True
                            url = urls[0]
                            self.tunnel_url_var.set(url)
                            add_log(f"[Tunnel] public URL: {url}")
                            add_log(f"[Tunnel] car device should set base_url to: {url}/v1")

                process.wait()
                add_log("[Tunnel] cloudflared process ended")
            except Exception as e:
                add_log(f"[Tunnel] error: {e}")

            self.tunnel_running = False
            self.tunnel_btn.config(text="Start Tunnel")
            self.tunnel_url_var.set("")
            self._update_status()

        threading.Thread(target=run_tunnel, daemon=True).start()

    def _stop_tunnel(self):
        if self.tunnel_process:
            self.tunnel_process.terminate()
            self.tunnel_process = None
        if self.tunnel_server:
            self.tunnel_server.shutdown()
            self.tunnel_server.server_close()
            self.tunnel_server = None
        self.tunnel_running = False
        self.tunnel_proxy_running = False
        add_log("[Tunnel] stopped")
        self.tunnel_btn.config(text="Start Tunnel")
        self.tunnel_url_var.set("")
        self._update_status()

    def _update_status(self):
        proxy_status = f"running on port {self.proxy_port_var.get()}" if self.proxy_running else "stopped"
        tunnel_status = f"running on port {self.tunnel_port_var.get()}" if self.tunnel_running else "stopped"
        self.status_var.set(f"ADB Proxy: {proxy_status} | Tunnel: {tunnel_status}")

    def _clear_log(self):
        log_buffer.clear()
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _refresh_logs(self):
        last_idx = getattr(self, "_last_log_idx", 0)
        if len(log_buffer) > last_idx:
            new_logs = list(log_buffer)[last_idx:]
            self._last_log_idx = len(log_buffer)
            self.log_text.config(state=tk.NORMAL)
            for msg in new_logs:
                ts = time.strftime("%H:%M:%S")
                self.log_text.insert(tk.END, f"{ts} {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        self.root.after(200, self._refresh_logs)


if __name__ == "__main__":
    root = tk.Tk()
    app = LLMProxyApp(root)
    root.mainloop()