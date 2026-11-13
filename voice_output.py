# -*- coding: utf-8 -*-
"""玄机 GUI · CosyVoice 语音输出 (WebSocket 直连)

2026-10-13 修：
  原本把模型/音色写死成 cosyvoice-v1 + longxiaoxia，官方一改版就整条嗓子哑掉，
  日志里反复出现 "Model not exist"。现改为候选列表依次回退，任一通即用，
  并把每次成功/失败都打出来，方便以后追责到具体是哪一组。
"""
import os, json, uuid
from websocket import create_connection
from typing import Optional

_E = "QWEN_API_KEY"
_P = _E + chr(61)

# 候选：(model, voice)，从前到后依次尝试，第一个成功的就用
_CANDIDATES = (
    ("cosyvoice-v2", "longxiaoxia_v2"),
    ("cosyvoice-v1", "longxiaoxia"),
)


def _load_key() -> str:
    k = os.environ.get(_E)
    if k:
        return k
    for bd in [os.path.dirname(__file__),
               os.path.join(os.path.dirname(__file__), "..", "openhuman")]:
        ep = os.path.join(bd, ".env")
        if os.path.isfile(ep):
            with open(ep, encoding="utf-8") as f:
                for ln in f:
                    s = ln.strip()
                    if s.startswith(_P):
                        p = s.split(chr(61), 1)
                        if len(p) >= 2 and p[1].strip():
                            return p[1].strip()
    raise RuntimeError("QWEN_API_KEY not found")


_K = _load_key()

_WS = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


class VoiceOutput:
    def synthesize(self, text: str) -> Optional[bytes]:
        text = (text or "").strip()
        if not text:
            return None
        errs = []
        for model, voice in _CANDIDATES:
            audio, err = self._try_one(model, voice, text)
            if audio:
                print("[vo] CosyVoice OK (%s / %s, %d bytes)" % (model, voice, len(audio)))
                return audio
            errs.append("%s / %s -> %s" % (model, voice, err))
        print("[vo] CosyVoice 全部候选失败: " + " ; ".join(errs))
        return None

    def _try_one(self, model, voice, text):
        ws = None
        try:
            ws = create_connection(_WS,
                header={"Authorization": "bearer " + _K}, timeout=120)
            tid = uuid.uuid4().hex
            run = {"header": {"task_id": tid, "streaming": "duplex", "action": "run-task"},
                   "payload": {"model": model, "task_group": "audio",
                               "task": "tts", "function": "SpeechSynthesizer",
                               "input": {"text": text},
                               "parameters": {"voice": voice, "format": "wav",
                                              "sample_rate": 44100}}}
            ws.send(json.dumps(run))
            ws.send(json.dumps({"header": {"task_id": tid, "action": "finish-task"},
                                "payload": {"input": {}}}))
            chunks = []
            while True:
                msg = ws.recv()
                if isinstance(msg, bytes):
                    chunks.append(msg)
                    continue
                d = json.loads(msg)
                ev = d.get("header", {}).get("event")
                if ev == "task-finished":
                    break
                if ev == "task-failed":
                    return None, str(d.get("header", {}).get("error_message", "task-failed"))
            audio = b"".join(chunks)
            if audio:
                return audio, ""
            return None, "empty audio"
        except Exception as e:
            return None, str(e)
        finally:
            try:
                if ws:
                    ws.close()
            except Exception:
                pass


if __name__ == "__main__":
    _vo = VoiceOutput()
    _a = _vo.synthesize("公子，我在。")
    print("PROBE:", ("OK %d bytes" % len(_a)) if _a else "FAILED")
