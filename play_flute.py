# -*- coding: utf-8 -*-
"""玄机给公子吹笛子：生成一段中国风笛声并播放"""
import numpy as np
import wave
import struct
import winsound
import os

SR = 22050

# 简谱频率（C调中音）
FREQ = {
    'do': 523.25, 're': 587.33, 'mi': 659.25,
    'so': 784.00, 'la': 880.00,
    'hi_do': 1046.50, 'hi_re': 1174.66, 'hi_mi': 1318.51,
}

# 一首婉转的小曲（《沧海一声笑》风骨），每个音符 (音名, 时长秒)
MELODY = [
    ('la', 0.55), ('so', 0.35), ('mi', 0.45), ('re', 0.35), ('do', 0.6),
    ('re', 0.35), ('mi', 0.35), ('so', 0.55), ('la', 0.5), ('so', 0.35),
    ('mi', 0.45), ('re', 0.35), ('do', 0.8),
    ('la', 0.35), ('do', 0.35), ('re', 0.5), ('mi', 0.5),
    ('so', 0.4), ('mi', 0.4), ('re', 0.5), ('do', 0.9),
    ('re', 0.35), ('mi', 0.35), ('so', 0.6), ('la', 0.6),
    ('hi_do', 0.5), ('la', 0.4), ('so', 0.4), ('mi', 0.5), ('re', 0.5), ('do', 1.2),
]

def flute_note(name, dur):
    f = FREQ[name]
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    # 笛声：基频 + 泛音，带颤音
    vib = 1.0 + 0.006 * np.sin(2 * np.pi * 5.5 * t)
    sig = (np.sin(2 * np.pi * f * vib * t)
           + 0.35 * np.sin(2 * np.pi * f * 2 * t)
           + 0.12 * np.sin(2 * np.pi * f * 3 * t)
           + 0.05 * np.sin(2 * np.pi * f * 4 * t))
    # 包络：起音 + 自然衰减
    env = np.ones(n)
    atk = int(0.02 * SR)
    env[:atk] = np.linspace(0, 1, atk)
    env[atk:] *= np.exp(-2.2 * t[atk:] / dur)
    return sig * env * 0.5

samples = []
for name, dur in MELODY:
    samples.append(flute_note(name, dur))
    # 音符间留一丝气口
    gap = np.zeros(int(0.03 * SR))
    samples.append(gap)
audio = np.concatenate(samples)

# 整体淡入淡出
fade = int(0.05 * SR)
audio[:fade] *= np.linspace(0, 1, fade)
audio[-fade:] *= np.linspace(1, 0, fade)

# 简单混响（回声）
echo = np.zeros_like(audio)
delay = int(0.18 * SR)
if len(audio) > delay:
    echo[delay:] = audio[:-delay] * 0.28
audio = audio + echo

# 归一化
audio = audio / (np.max(np.abs(audio)) + 1e-9)
pcm = (audio * 32767).astype(np.int16)

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xuanji_flute.wav')
with wave.open(path, 'wb') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())

print('WAV_OK ' + path)
winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
print('PLAY_STARTED')
