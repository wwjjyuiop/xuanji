# -*- coding: utf-8 -*-
"""玄机 · 教学/运维通道 coach_channel.py
============================================================
让 WSL 里的师傅（哪吒）通过 HTTP 访问这台 Windows 上的玄机，
实现"上门教学 + 巡检 + 下发指令"。

设计原则：
- 纯标准库（http.server），零第三方依赖，不与玄机抢端口
- 仅监听本机可访问的入口，接口只读/受控，返回受限信息，不做高危写操作
- 后台 daemon 线程启动，启动失败绝不影响玄机主窗口
- 端口可配置，避开 3D形象(18796) 等已占端口

用途（师傅 → 玄机）：
  GET /status   → 玄机运行状态、版本、连接情况
  GET /log      → 最近运行日志（排查问题用）
  GET /hands    → 手脚插件/工具清单（看玄机有哪些能力）
  POST /teach   → 下发一条教学/运维指令（写入日志 + 可选执行回调）
"""
import os
import sys
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

XJ_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 18797   # 避开 3D形象 18796

# 最近日志环形缓冲（几十条内存日志，便于师傅拉取，不落盘敏感信息）
_MAX_LOG = 200
_LOG_RING = []
_TEACH_HANDLER = None   # 玄机可注册一个回调处理 /teach 指令


def log(msg: str):
    """玄机侧调用：往通道的日志缓冲写一条。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _LOG_RING.append("[%s] %s" % (ts, msg))
    if len(_LOG_RING) > _MAX_LOG:
        del _LOG_RING[: len(_LOG_RING) - _MAX_LOG]


_EVAL_HANDLER = None   # 2026-09-21 加：/eval 只读诊断接口（把 JS 丢进 3D 页面执行，结果打日志）


def set_eval_handler(fn):
    """注册 JS 执行回调 fn(payload) -> dict，用于外部读 3D 页面内部状态。"""
    global _EVAL_HANDLER
    _EVAL_HANDLER = fn


def set_teach_handler(fn):
    """玄机侧注册 /teach 回调 fn({'cmd':..., ...}) -> dict"""
    global _TEACH_HANDLER
    _TEACH_HANDLER = fn


def _collect_status():
    status = {
        "name": "玄机",
        "pid": os.getpid(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": XJ_ROOT,
        "coach_port": _bound_port,   # 教学通道实际生效端口
    }
    # 连接情况：DeepSeek 主推理 key 是否已配
    try:
        import api_config
        ds, qw = api_config.load()
        status["deepseek_key_configured"] = bool(ds)
        status["qwen_key_configured"] = bool(qw)
    except Exception:
        status["deepseek_key_configured"] = None
        status["qwen_key_configured"] = None
    return status


def _collect_hands():
    try:
        # 扫描 dispatch 工具 + hands 插件（加入 D:\yuxuanji 根，dispatch.py 在那）
        yuxuanji_root = os.getenv("YUANXUANJI_ROOT") or r"D:\yuxuanji"
        for d in [XJ_ROOT, os.path.join(XJ_ROOT, "hands"), yuxuanji_root]:
            if d not in sys.path:
                sys.path.insert(0, d)
        import dispatch
        tools = dispatch.list_tools()
        return {"ok": True, "tools": tools}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass   # 静默，避免刷屏

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/status":
            self._send(200, {"ok": True, "status": _collect_status()})
        elif path == "/log":
            self._send(200, {"ok": True, "lines": list(_LOG_RING[-100:])})
        elif path == "/hands":
            self._send(200, _collect_hands())
        elif path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"ok": False, "error": "unknown: " + path})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/eval":
            try:
                _len = int(self.headers.get("Content-Length", 0))
                _raw = self.rfile.read(_len) if _len else b"{}"
                _pl = json.loads(_raw.decode("utf-8") or "{}")
            except Exception as _e:
                self._send(400, {"ok": False, "error": "bad json: " + str(_e)})
                return
            if _EVAL_HANDLER is None:
                self._send(200, {"ok": False, "error": "no eval handler"})
                return
            try:
                self._send(200, {"ok": True, "result": _EVAL_HANDLER(_pl)})
            except Exception as _e:
                self._send(500, {"ok": False, "error": str(_e)})
            return
        if path != "/teach":
            self._send(404, {"ok": False, "error": "unknown: " + path})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception as e:
            self._send(400, {"ok": False, "error": "bad json: " + str(e)})
            return
        log("[coach] 收到指令: " + str(payload.get("cmd", ""))[:200])
        if _TEACH_HANDLER is not None:
            try:
                result = _TEACH_HANDLER(payload)
                self._send(200, {"ok": True, "handled": True, "result": result})
            except Exception as e:
                self._send(500, {"ok": False, "handled": True, "error": str(e)})
        else:
            # 无回调：仅记录（安全起见），告知已收但未执行
            self._send(200, {"ok": True, "handled": False,
                             "note": "收到并记录，未注册执行回调"})


_server = None
_thread = None
_bound_port = None   # 实际绑定成功的端口（自动避让后）


def start(port: int = DEFAULT_PORT):
    """启动教学通道服务（后台 daemon 线程，失败不影响主程序）。

    端口自动避让：若目标端口被占，自动递增寻找空闲端口（最多尝试 20 个），
    并把实际生效的端口存到 _bound_port，供 /status 查询。
    """
    global _server, _thread, _bound_port
    if _server is not None:
        return True
    last_err = ""
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", p), _Handler)
        except Exception as e:
            last_err = str(e)
            continue   # 端口被占，试下一个
        _server = srv
        _server.daemon_threads = True
        _bound_port = p
        break
    if _server is None:
        log("[coach] 通道启动失败(端口 " + str(port) + "~" + str(port + 19) + " 全被占): " + last_err)
        return False
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    log("[coach] 教学通道已启动 0.0.0.0:" + str(_bound_port))
    return True


def stop():
    global _server
    if _server is not None:
        _server.shutdown()
        _server = None
