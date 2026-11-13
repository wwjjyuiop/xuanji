"""
玄机 · 语音引擎模块 voice/voice_engine.py（方案二拆分第4刀）
VoiceEngine 从 window.py 拆出，逻辑零改动仅移位置。
依赖 sentiment 模块做情感分析，依赖外部 voice_in/voice_out。
"""

import threading
import time
import io
import struct
import wave
from collections import deque

import sentiment as _sent

# 音频常量（拆分时从 window.py 带出，供 VoiceEngine 使用）
SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES_PER_BUFFER = 1024
DTYPE = "int16"
VOICE_THRESHOLD = 300        # 语音启动阈值：恢复原始值（曾误调1200导致听不到）
SILENCE_DURATION = 1.5       # 恢复原始值（曾误调1.8）
MIN_VOICE_DURATION = 0.5     # 恢复原始值（曾误调0.8）
MAX_RECORD_DURATION = 15
VOICE_CONFIRM_CHUNKS = 2     # 恢复原始值（曾误调8导致铃声不触发）
INTERRUPT_THRESHOLD = 2200   # 插话阈值：须高于喇叭回声，防自己打断自己
INTERRUPT_CONFIRM = 4        # 连续4块（约0.26秒）超阈值才算插话，防误触
# 播放锁（语音播报与录音互斥）
_PLAYBACK_LOCK = threading.Lock()

# 语音依赖（无 key 时允许降级，不阻塞窗口）
try:
    import sounddevice as sd
    import numpy as np
    _AUDIO_OK = True
except ImportError:
    sd = None
    np = None
    _AUDIO_OK = False

# 玄机对话入口（拆分时从 window.py 带出，供语音识别后发消息）
from connector import send_message


def _voice_guard():
    """若降级（无 sd/np），抛出清晰错误提示。"""
    if not _AUDIO_OK:
        raise RuntimeError("语音引擎依赖(sounddevice/numpy)未安装，无法使用语音")


class VoiceEngine:

    def __init__(self, voice_in, voice_out):
        self._voice_in = voice_in
        self._voice_out = voice_out
        self._running = False
        self._thread = None
        self.on_state = None
        self.on_user_text = None
        self.on_bot_text = None
        self.on_error = None
        self.on_speaking = None
        self.on_emotion = None
        self.get_visual = None  # 摄像头开着时返回当前帧 JPEG base64（直接给 DeepSeek 看），否则None
        self._mon_stream = None  # 旁听流：只在播报时盯主人插话，不参与录音
        self._mon_amp = 0.0      # 旁听流最近一块的音量

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._notify_state("语音已开启")

    def stop(self):
        self._running = False
        self._notify_state("语音已关闭")

    def is_running(self):
        return self._running

    def _loop(self):
        ring = deque(maxlen=int(SAMPLE_RATE / FRAMES_PER_BUFFER * 1.0))

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype=DTYPE, blocksize=FRAMES_PER_BUFFER,
                device=1,
            )
            stream.start()
        except Exception as e:
            # 回退到默认设备
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=CHANNELS,
                    dtype=DTYPE, blocksize=FRAMES_PER_BUFFER,
                )
                stream.start()
            except Exception as e2:
                self._notify_error("麦克风失败: " + str(e2))
                self._running = False
                return

        self._start_monitor()

        while self._running:
            try:
                voice_buf = self._wait_voice(stream, ring)
                if voice_buf is None:
                    continue

                self._notify_state("聆听中...")
                # 用户说话时形象保持闭嘴——speaking 只应绑定 AI 播放语音（2026-08-16 修复）
                if self.on_speaking:
                    self.on_speaking(False)

                frames = self._record(stream, ring)
                if frames is None:
                    continue

                all_frames = list(voice_buf) + frames
                wav = self._to_wav(all_frames)

                try:
                    with open("D:/yuxuanji/xuanji-gui/_last_voice.wav", "wb") as _fwav:
                        _fwav.write(wav)
                except:
                    pass

                self._notify_state("理解中...")
                text = self._voice_in.transcribe_audio(wav)
                if not text or not text.strip():
                    self._notify_state("没听清，再说一遍？")
                    continue

                if self.on_user_text:
                    self.on_user_text(text)

                self._notify_state("思考中...")
                image = None
                if self.get_visual:
                    image = self.get_visual()
                reply = send_message(text, image=image)
                if reply is None:
                    self._notify_error("连接异常")
                    continue

                if self.on_bot_text:
                    self.on_bot_text(reply)

                emotion = _sent.analyze_sentiment(reply)
                if self.on_emotion:
                    self.on_emotion(emotion)

                self._notify_state("说话中...")
                if self.on_speaking:
                    self.on_speaking(True)
                _cut = self._play(reply, stream)
                if self.on_speaking:
                    self.on_speaking(False)
                if _cut:
                    # 被打断：不歇那1.5秒，马上掉头听主人把话说完
                    self._notify_state("听见你了，说吧...")
                    continue
                time.sleep(1.5)

            except Exception as e:
                self._notify_error(str(e))
                time.sleep(0.5)

        self._stop_monitor()
        try:
            stream.stop()
            stream.close()
        except:
            pass

    def _start_monitor(self):
        """另开一路只听不用的输入流，专盯播报时主人有没有插话。
        开不起来就静静放弃，绝不拖累正常播报。"""
        if not _AUDIO_OK:
            return
        for dev in (1, None):
            try:
                self._mon_stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=CHANNELS,
                    dtype=DTYPE, blocksize=FRAMES_PER_BUFFER,
                    device=dev, callback=self._mon_cb,
                )
                self._mon_stream.start()
                return
            except Exception:
                self._mon_stream = None
        print("[旁听] 开不起来，插话功能暂不可用，播报不受影响")

    def _mon_cb(self, indata, frames, time_info, status):
        try:
            self._mon_amp = float(np.max(np.abs(indata)))
        except Exception:
            self._mon_amp = 0.0

    def _stop_monitor(self):
        try:
            if self._mon_stream is not None:
                self._mon_stream.stop()
                self._mon_stream.close()
        except Exception:
            pass
        self._mon_stream = None

    def _wait_voice(self, stream, ring):
        chunks = 0
        buf = deque(maxlen=int(SAMPLE_RATE / FRAMES_PER_BUFFER * 0.5))
        tick = 0
        while self._running:
            data = stream.read(FRAMES_PER_BUFFER)[0]
            ring.append(data)
            amp = float(np.max(np.abs(data)))
            tick += 1
            if tick % 50 == 0:
                self._notify_state("amp=" + str(int(amp)) + " thr=" + str(VOICE_THRESHOLD))
            if amp > VOICE_THRESHOLD:
                chunks += 1
                buf.append(data)
                if chunks >= VOICE_CONFIRM_CHUNKS:
                    return list(buf)
            else:
                chunks = 0
                buf.clear()
        return None

    def _record(self, stream, ring):
        frames = []
        silent = 0
        limit = int(SAMPLE_RATE / FRAMES_PER_BUFFER * SILENCE_DURATION)
        max_c = int(SAMPLE_RATE / FRAMES_PER_BUFFER * MAX_RECORD_DURATION)
        had_voice = False
        for _ in range(max_c):
            if not self._running:
                return None
            data = stream.read(FRAMES_PER_BUFFER)[0]
            frames.append(data)
            ring.append(data)
            amp = float(np.max(np.abs(data)))
            if amp > VOICE_THRESHOLD:
                had_voice = True
                silent = 0
            else:
                silent += 1
                if had_voice and silent > limit:
                    break
        dur = len(frames) * FRAMES_PER_BUFFER / SAMPLE_RATE
        if dur < MIN_VOICE_DURATION or not had_voice:
            return None
        return frames

    def _play(self, text, listen_stream):
        # 过滤括号动作描述（全角/半角括号）
        import re
        clean = re.sub(r'[（(][^）)]*[）)]', '', text)
        clean = clean.strip()
        if not clean:
            clean = text  # 全删了就用原文
        audio = self._voice_out.synthesize(clean)
        if audio is None:
            return
        if audio[:4] == b"RIFF":
            sr = struct.unpack("<I", audio[24:28])[0]
            pcm = audio[44:]
        else:
            sr = 22050
            pcm = audio
        arr = np.frombuffer(pcm, dtype=np.int16)
        off = 0
        interrupted = False
        _cooldown = int(sr / FRAMES_PER_BUFFER * 0.6)   # 起播0.6秒内不判，避开爆音与回声
        _loud_run = 0
        try:
            out = sd.OutputStream(samplerate=sr, channels=1, dtype=DTYPE, blocksize=FRAMES_PER_BUFFER)
            out.start()
            while off < len(arr) and self._running:
                chunk = arr[off:off + FRAMES_PER_BUFFER]
                out.write(chunk)
                off += FRAMES_PER_BUFFER
                # 2026-10-15 依公子嘱咐：嘴不停，耳朵也不关——边播边听
                if self._mon_stream is not None and off > _cooldown:
                    if self._mon_amp > INTERRUPT_THRESHOLD:
                        _loud_run += 1
                    else:
                        _loud_run = 0
                    if _loud_run >= INTERRUPT_CONFIRM:
                        interrupted = True
                        print("[打断] 听见主人开口 amp=" + str(int(self._mon_amp)) + "，掐断播报")
                        break
            out.stop()
            out.close()
        except Exception as e:
            print("[播放] " + str(e))
        return interrupted

    def _to_wav(self, frames):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(np.concatenate(frames).tobytes())
        return buf.getvalue()

    def _notify_state(self, s):
        # on_state 现在是 Signal.emit（跨线程安全），直接调用
        if self.on_state:
            self.on_state(s)

    def _notify_error(self, s):
        if self.on_error:
            self.on_error(s)


# ═══════════════════════════════════════════════
#  主窗口
# ═══════════════════════════════════════════════

