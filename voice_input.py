"""
玄机 GUI · 语音识别模块
使用千问3.5-Omni多模态模型直接理解语音（不走paraformer ASR）

用法：
    recognizer = VoiceInput()
    text = recognizer.transcribe_audio(wav_bytes)
"""

import os
import io
import wave
import json
import base64
import urllib.request
import urllib.error
from typing import Optional



def _find_qwen_key() -> str:
    key = os.environ.get('QWEN_API_KEY')
    if key:
        return key
    for base_dir in [os.path.dirname(__file__),
                     os.path.join(os.path.dirname(__file__), '..', 'openhuman')]:
        env_path = os.path.join(base_dir, '.env')
        if os.path.isfile(env_path):
            try:
                with open(env_path, encoding='utf-8') as f:
                    for line in f:
                        s = line.strip()
                        if s.startswith('QWEN_API_KEY='):
                            p = s.split('=', 1)
                            if len(p) >= 2 and p[1].strip():
                                return p[1].strip()
            except OSError:
                continue
    raise RuntimeError('[voice_input] QWEN_API_KEY not found')

class VoiceInput:
    """语音识别：接收WAV数据 → 千问多模态模型 → 返回文字"""

    def __init__(self):
        self.api_key = _find_qwen_key()

    def transcribe_audio(self, audio_data: bytes) -> Optional[str]:
        """
        将WAV音频数据发送给千问3.5-Omni多模态模型直接理解

        参数：
            audio_data: WAV格式的完整音频数据（含44字节头）

        返回：
            识别文字，失败返回 None
        """
        # 自动放大音量到正常水平
        try:
            import numpy as np
            with wave.open(io.BytesIO(audio_data), "rb") as wf:
                sr = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            peak = float(np.max(np.abs(arr)))
            if peak > 0 and peak < 15000:
                gain = 20000.0 / peak
                arr = np.clip(arr * gain, -32767, 32767).astype(np.int16)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    wf.writeframes(arr.tobytes())
                audio_data = buf.getvalue()
                print(f"[语音识别] 音量放大: {peak:.0f} -> 20000 (增益 {gain:.1f}x)")
        except Exception as e:
            print(f"[语音识别] 音量处理跳过: {e}")

        # 转base64
        b64 = base64.b64encode(audio_data).decode()

        # 调用千问3.5-Omni多模态API
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        payload = {
            "model": "qwen3.5-omni-flash",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"text": "请识别这段音频说了什么，直接输出文字内容，不要多余解释"},
                            {"audio": f"data:audio/wav;base64,{b64}"}
                        ]
                    }
                ]
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json"
            },
            method="POST"
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            choices = result.get("output", {}).get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", [])
                if content and isinstance(content, list):
                    texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                    text = " ".join(t for t in texts if t)
                    if text.strip():
                        print(f"[语音识别] 结果: {text[:80]}...")
                        return text
                elif isinstance(content, str):
                    if content.strip():
                        print(f"[语音识别] 结果: {content[:80]}...")
                        return content

            print("[语音识别] 无识别结果")
            return None

        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"[语音识别] API错误 {e.code}: {body[:200]}")
            return None
        except Exception as e:
            print(f"[语音识别] 调用失败: {e}")
            return None
