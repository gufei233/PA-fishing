# mark_points.py
# -*- coding: utf-8 -*-
"""
把 PA-fishing 脚本中的像素坐标可视化标到三张示例图上
依赖：pip install opencv-python numpy
"""

import cv2 as cv
import numpy as np
from pathlib import Path

# ───────── 配置（按需修改） ──────────────────────────
class Cfg:
    # === 文件名 ===
    gauge_img   = "gauge.png"     # 拉力盘整图
    bucket_img  = "bucket.png"    # 鱼桶整图
    banner_img  = "banner.png"    # 黄色提示框整图

    # === 像素坐标 ===
    tick_coords = {               # Z1~Z4
        1: (808, 1016),
        2: (872,  952),
        3: (961,  929),
        4: (1048, 951),
    }
    bucket_coords = {             # 鱼桶 top-yellow ×2, bottom-beige ×2
        "top":    [(1479, 336), (1768, 337)],
        "bottom": [(1449, 878), (1814, 880)],
    }
    banner_coords = [(1200, 65), (1210, 153)]   # 提示框框两点

    # === 绘图参数 ===
    radius   = 10                 # 圆点半径
    thickness= 2                  # 线宽
    font     = cv.FONT_HERSHEY_SIMPLEX
    fscale   = 0.6
    fthick   = 2
    color    = (0, 0, 255)        # BGR → 红
CFG = Cfg()
# ───────────────────────────────────────────────────

def mark_and_save(img_path: Path, points, labels, suffix="_marked"):
    if not img_path.exists():
        print(f"[WARN] 找不到图片 {img_path}")
        return
    img = cv.imread(str(img_path))
    if img is None:
        print(f"[WARN] 读取失败 {img_path}")
        return

    for (x, y), text in zip(points, labels):
        cv.circle(img, (x, y), CFG.radius, CFG.color, CFG.thickness, cv.LINE_AA)
        cv.putText(img, text, (x+CFG.radius+4, y-4),
                   CFG.font, CFG.fscale, CFG.color, CFG.fthick, cv.LINE_AA)

    out_path = img_path.with_stem(img_path.stem + suffix)
    cv.imwrite(str(out_path), img)
    print(f"[OK] {out_path} 已保存")

def main():
    # 1) 拉力盘 4 点
    gauge_pts   = list(CFG.tick_coords.values())
    gauge_labels= [f"Z{i}" for i in CFG.tick_coords.keys()]
    mark_and_save(Path(CFG.gauge_img), gauge_pts, gauge_labels)

    # 2) 鱼桶 4 点
    bucket_pts  = CFG.bucket_coords["top"] + CFG.bucket_coords["bottom"]
    bucket_labels = ["Top-1", "Top-2", "Bot-1", "Bot-2"]
    mark_and_save(Path(CFG.bucket_img), bucket_pts, bucket_labels)

    # 3) 黄框 2 点
    banner_pts  = CFG.banner_coords
    banner_labels = ["B-1", "B-2"]
    mark_and_save(Path(CFG.banner_img), banner_pts, banner_labels)

if __name__ == "__main__":
    main()
