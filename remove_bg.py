"""抠图去背景：rembg 批量处理7张立绘"""
import os, sys
from pathlib import Path
from PIL import Image
from rembg import remove, new_session

ASSETS_DIR = Path(__file__).parent / "assets"
OUTPUT_DIR = Path(__file__).parent / "assets_cutout"

# 使用u2net模型（质量高，但第一次运行会下载~200MB模型）
# 可选: u2net_human_seg（专门针对人像，更准）
print("正在准备人像抠图模型...")
session = new_session("u2net_human_seg")

OUTPUT_DIR.mkdir(exist_ok=True)

exts = ('.png', '.jpg', '.jpeg')
files = sorted(f for f in os.listdir(ASSETS_DIR) if f.lower().endswith(exts))

for fname in files:
    in_path = ASSETS_DIR / fname
    stem = Path(fname).stem
    out_path = OUTPUT_DIR / f"{stem}.png"  # 统一输出透明PNG

    if out_path.exists():
        print(f"  ⏭️  {fname} 已存在，跳过")
        continue

    print(f"  🔄 {fname} ... ", end="", flush=True)
    img = Image.open(in_path)
    
    # 转RGBA
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # 抠图
    cutout = remove(img, session=session)
    
    # 保存
    cutout.save(out_path, "PNG")
    print(f"✅ {out_path.name}")

print(f"\n🎉 完成！{len(files)} 张图输出到: {OUTPUT_DIR}")
