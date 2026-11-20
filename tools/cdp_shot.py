# -*- coding: utf-8 -*-
"""最小 CDP 客户端（标准库）：eval / screenshot。"""
import base64
import json
import os
import socket
import struct
import sys
import urllib.request

PORT = int(os.environ.get("CDP_PORT", "9333"))
# 本地调试口不能走系统代理：代理没开时 urllib 会抛 WinError 10061，
# 而 curl 直连却是通的，很容易误判成「Chrome 没起来」。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(path):
    with _OPENER.open(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class WS:
    def __init__(self, url):
        # ws://host:port/devtools/page/xxx
        _, _, rest = url.partition("://")
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), 10)
        self.sock.settimeout(90)          # 牌图多时截图会更慢，别用 10 秒卡死
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        assert b"101" in buf.split(b"\r\n")[0], buf[:200]
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.mid = 0

    def _read(self, n):
        while len(self.buf) < n:
            d = self.sock.recv(65536)
            if not d:
                raise IOError("closed")
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj):
        data = json.dumps(obj).encode()
        hdr = bytearray([0x81])
        ln = len(data)
        if ln < 126:
            hdr.append(0x80 | ln)
        elif ln < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", ln)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", ln)
        mask = os.urandom(4)
        hdr += mask
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        b1, b2 = self._read(2)
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(ln)
        return json.loads(payload.decode("utf-8"))

    def call(self, method, params=None, timeout_msg=""):
        self.mid += 1
        mid = self.mid
        self.send({"id": mid, "method": method, "params": params or {}})
        for _ in range(200):
            msg = self.recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise RuntimeError("no reply " + timeout_msg)


def main():
    cmd = sys.argv[1]
    pages = [t for t in http_json("/json/list") if t.get("type") == "page"]
    page = pages[0]
    ws = WS(page["webSocketDebuggerUrl"])
    if cmd == "eval":
        r = ws.call("Runtime.evaluate",
                    {"expression": sys.argv[2], "returnByValue": True,
                     "awaitPromise": True})
        print(json.dumps(r.get("result", {}).get("value"), ensure_ascii=False))
    elif cmd == "call":
        r = ws.call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {})
        print(json.dumps(r)[:200])
    elif cmd == "shot":
        out = sys.argv[2]
        w = int(sys.argv[3]) if len(sys.argv) > 3 else 1747
        h = int(sys.argv[4]) if len(sys.argv) > 4 else 945
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        r = ws.call("Page.captureScreenshot", {"format": "png"})
        open(out, "wb").write(base64.b64decode(r["data"]))
        print("saved", out)


if __name__ == "__main__":
    main()
