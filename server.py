#!/usr/bin/env python3
"""岔路 · 竖切服务器——静态页 + GLM 代理（key 留在本机, 不进前端）。

用法:  py -3 server.py  →  http://127.0.0.1:8777
模型:  默认 glm-4-flash（免费）; 环境变量 BR_MODEL 可换（如 glm-4.5-air）。
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
KEY = os.environ.get("ZHIPU_API_KEY")
MODEL = os.environ.get("BR_MODEL", "glm-4-flash")
END_MODEL = os.environ.get("BR_END_MODEL", "glm-4.5-air")  # 终局信单独用强模型
API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
TTS_VOICE = os.environ.get("BR_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_cache")

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
        ".css": "text/css", ".png": "image/png", ".jpg": "image/jpeg",
        ".woff2": "font/woff2", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静掉逐请求日志, 只留错误
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _tts(self):
        """edge-tts 合成林晚的语音（磁盘缓存, 同文本不重复请求微软）。"""
        import asyncio
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            req = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            req = json.loads(raw.decode("gbk", "replace"))  # 控制台 curl 兜底
        text = str(req.get("text", ""))[:600]
        import hashlib
        cache = os.path.join(TTS_DIR, hashlib.md5((TTS_VOICE + text).encode()).hexdigest() + ".mp3")
        os.makedirs(TTS_DIR, exist_ok=True)
        if not os.path.isfile(cache):
            try:
                import edge_tts
                async def run():
                    com = edge_tts.Communicate(text, TTS_VOICE, rate="-6%")
                    await com.save(cache)
                asyncio.run(run())
            except Exception as e:
                self._send(502, json.dumps({"error": f"tts: {e}"}).encode(), "application/json")
                return
        with open(cache, "rb") as f:
            self._send(200, f.read(), "audio/mpeg")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        fp = os.path.join(ROOT, path.lstrip("/"))
        if not os.path.isfile(fp):
            self._send(404, b"not found", "text/plain")
            return
        ext = os.path.splitext(fp)[1].lower()
        with open(fp, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def do_POST(self):
        if self.path == "/api/tts":
            self._tts()
            return
        if self.path != "/api/chat":
            self._send(404, b"not found", "text/plain")
            return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            req = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            req = json.loads(raw.decode("gbk", "replace"))  # Windows 控制台 curl 兜底
        if not KEY:
            self._send(500, json.dumps({"error": "ZHIPU_API_KEY 未设置"}).encode(),
                       "application/json")
            return
        model = END_MODEL if req.get("ending") else MODEL
        body = json.dumps({"model": model, "messages": req["messages"],
                           "temperature": 0.9, "max_tokens": 1200}).encode()
        rq = urllib.request.Request(API, data=body, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=90) as r:
                resp = json.loads(r.read())
            text = resp["choices"][0]["message"]["content"]
            self._send(200, json.dumps({"text": text}).encode(), "application/json")
        except Exception as e:  # 网络/额度/安全拒答——原样透传给前端处理
            self._send(502, json.dumps({"error": str(e)}).encode(), "application/json")


if __name__ == "__main__":
    print(f"岔路 · 竖切  →  http://127.0.0.1:8777   (model={MODEL})")
    ThreadingHTTPServer(("127.0.0.1", 8777), Handler).serve_forever()
