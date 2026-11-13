"""径向渐变融合去背景（快速版：用numpy向量化）"""
import os
from pathlib import Path
import numpy as np
from PIL import Image

ASSETS_DIR = Path(__file__).parent / "assets"
OUTPUT_DIR = Path(__file__).parent / "assets_cutout"
OUTPUT_DIR.mkdir(exist_ok=True)

exts = ('.png', '.jpg', '.jpeg')
files = sorted(f for f in os.listdir(ASSETS_DIR) if f.lower().endswith(exts))

for fname in files:
    in_path = ASSETS_DIR / fname
    stem = Path(fname).stem
    out_path = OUTPUT_DIR / f"{stem}.png"
    
    if out_path.exists():
        print(f"  ⏭️  {fname} 已存在")
        continue
    
    print(f"  🔄 {fname} ... ", end="", flush=True)
    img = Image.open(in_path).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    
    # 人物中心坐标（稍偏上，因为是半身像）
    cx, cy = w // 2, int(h * 0.40)
    
    # 计算每个像素到中心的距离
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    
    # 内圈半径：完全保留
    inner_r = min(w, h) * 0.38
    # 外圈半径：完全透明
    outer_r = max(w, h) * 0.62
    
    # 生成alpha通道
    alpha = np.ones((h, w), dtype=np.float32) * 255
    
    # 边缘: 平滑过渡
    mask_fade = (dist > inner_r) & (dist < outer_r)
    t = (dist[mask_fade] - inner_r) / (outer_r - inner_r)
    # 用smoothstep曲线
    alpha[mask_fade] = 255 * (1.0 - t * t * (3 - 2 * t))
    alpha[dist >= outer_r] = 0
    
    arr[:, :, 3] = alpha.astype(np.uint8)
    
    out = Image.fromarray(arr, "RGBA")
    out.save(out_path, "PNG")
    print(f"✅ {out_path.name} ({w}x{h})")

print(f"\n🎉 完成！{len(files)} 张 -> {OUTPUT_DIR}")
