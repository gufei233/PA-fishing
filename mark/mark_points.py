# mark_points.py
# -*- coding: utf-8 -*-
"""
PA-fishing 坐标可视化脚本
----------------------------------
1. 自动检测图片分辨率并按需缩放标注；
2. 标注完成后，为每张图片分别生成坐标结果文件：
      gauge_<WxH>.py      → tick_coords
      bucket_<WxH>.py     → bucket_coords
      banner_<WxH>.py     → banner_coords

依赖：pip install opencv-python numpy
"""

import cv2 as cv
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

# ───────── 配置 ─────────────────────────────────────────────────────────
class Cfg:
    base_size = (1920, 1080)                 # 基准分辨率 (W0, H0)

    gauge_img  = "gauge.png"                 # 张力盘整图
    bucket_img = "bucket.png"                # 鱼桶整图
    banner_img = "banner.png"                # 黄色提示框整图

    tick_coords = {                          # 张力盘四点 (基于 base_size)
        1: (808, 1016), 2: (872,  952),
        3: (961,  929), 4: (1048, 951),
    }
    bucket_coords = {                        # 鱼桶上黄 2、下米白 2
        "top":    [(1479, 336), (1768, 337)],
        "bottom": [(1509,  848), (1734,  848)],
    }
    banner_coords = [(1200, 65), (1210, 153)]  # 黄框 2 点

    # 绘图参数
    radius = 10
    thickness = 2
    font = cv.FONT_HERSHEY_SIMPLEX
    fscale = 0.6
    fthick = 2
    color = (0, 0, 255)                      # BGR 红色
CFG = Cfg()
# ────────────────────────────────────────────────────────────────────────

# ───────── 工具函数 ─────────────────────────────────────────────────────
def _scale_point(pt: Tuple[int, int], w: int, h: int,
                 base_w: int, base_h: int) -> Tuple[int, int]:
    sx, sy = w / base_w, h / base_h
    x, y = int(round(pt[0] * sx)), int(round(pt[1] * sy))
    return max(0, min(w - 1, x)), max(0, min(h - 1, y))

def _scale_points(points: Sequence[Tuple[int, int]], w: int, h: int,
                  base_w: int, base_h: int) -> List[Tuple[int, int]]:
    return [_scale_point(p, w, h, base_w, base_h) for p in points]

def mark_and_save(img_path: Path,
                  points: Sequence[Tuple[int, int]],
                  labels: Sequence[str],
                  suffix: str = "_marked") -> Tuple[List[Tuple[int, int]], Tuple[int, int]]:
    """标注并保存，返回使用的坐标列表 & 分辨率 (w,h)。"""
    if not img_path.exists():
        print(f"[WARN] 找不到图片 {img_path}")
        return [], (0, 0)

    img = cv.imread(str(img_path))
    if img is None:
        print(f"[WARN] 读取失败 {img_path}")
        return [], (0, 0)

    h, w = img.shape[:2]
    base_w, base_h = CFG.base_size
    need_scale = (w, h) != (base_w, base_h)

    pts_use = _scale_points(points, w, h, base_w, base_h) if need_scale else list(points)

    note = "≠ 基准，已按比例换算" if need_scale else "为基准尺寸，直接使用原坐标"
    print(f"[INFO] {img_path.name}: 检测到分辨率 {w}x{h}，{note}。")

    for (x, y), text in zip(pts_use, labels):
        cv.circle(img, (x, y), CFG.radius, CFG.color, CFG.thickness, cv.LINE_AA)
        cv.putText(img, text, (x + CFG.radius + 4, y - 4),
                   CFG.font, CFG.fscale, CFG.color, CFG.fthick, cv.LINE_AA)

    out_path = img_path.with_stem(img_path.stem + suffix)
    cv.imwrite(str(out_path), img)
    print(f"[OK] {out_path} 已保存")
    return pts_use, (w, h)

def write_coord_file(kind: str,
                     coords,
                     res: Tuple[int, int]) -> None:
    """根据 kind 写入单独坐标文件。"""
    if res == (0, 0):
        print(f"[WARN] 跳过 {kind}，无有效分辨率。")
        return

    w, h = res
    fname = f"{kind}_{w}x{h}.py"
    lines = [
        "from typing import Dict, List, Tuple",
        "",
    ]

    if kind == "gauge":
        lines.append("# 张力盘（拉力盘）四点")
        lines.append("tick_coords: Dict[int, Tuple[int, int]] = {")
        for idx, (x, y) in enumerate(coords, start=1):
            lines.append(f"    {idx}: ({x}, {y}),")
        lines.append("}")
    elif kind == "bucket":
        top, bottom = coords[:2], coords[2:]
        lines.append("# 鱼桶“可见”判定（上 2 黄、下 2 米白）")
        lines.append("bucket_coords: Dict[str, List[Tuple[int, int]]] = {")
        lines.append("    \"top\": [")
        for (x, y) in top:
            lines.append(f"        ({x}, {y}),")
        lines.append("    ],")
        lines.append("    \"bottom\": [")
        for (x, y) in bottom:
            lines.append(f"        ({x}, {y}),")
        lines.append("    ],")
        lines.append("}")
    elif kind == "banner":
        lines.append("# 上鱼黄色提示框位置（2 点同时为黄）")
        lines.append("banner_coords: List[Tuple[int, int]] = [")
        for (x, y) in coords:
            lines.append(f"    ({x}, {y}),")
        lines.append("]")
    else:
        return

    Path(fname).write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] 坐标已输出至文件 {fname}")

# ───────── 主入口 ───────────────────────────────────────────────────────
def main():
    # —— 1) gauge ——
    gauge_pts_base = [CFG.tick_coords[k] for k in sorted(CFG.tick_coords)]
    gauge_labels   = [f"Z{k}" for k in sorted(CFG.tick_coords)]
    gauge_pts_scaled, gauge_res = mark_and_save(Path(CFG.gauge_img),
                                                gauge_pts_base, gauge_labels)
    write_coord_file("gauge", gauge_pts_scaled, gauge_res)

    # —— 2) bucket ——
    bucket_pts_base = CFG.bucket_coords["top"] + CFG.bucket_coords["bottom"]
    bucket_labels   = ["Top-1", "Top-2", "Bot-1", "Bot-2"]
    bucket_pts_scaled, bucket_res = mark_and_save(Path(CFG.bucket_img),
                                                  bucket_pts_base, bucket_labels)
    write_coord_file("bucket", bucket_pts_scaled, bucket_res)

    # —— 3) banner ——
    banner_pts_base = CFG.banner_coords
    banner_labels   = ["B-1", "B-2"]
    banner_pts_scaled, banner_res = mark_and_save(Path(CFG.banner_img),
                                                  banner_pts_base, banner_labels)
    write_coord_file("banner", banner_pts_scaled, banner_res)

if __name__ == "__main__":
    main()
