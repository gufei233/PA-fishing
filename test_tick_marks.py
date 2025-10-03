# -*- coding: utf-8 -*-
"""
精确坐标颜色识别
- 核心逻辑: 直接在用户提供的1920x1080截屏图片上，
  使用用户提供的精确绝对坐标进行颜色检测。
- 结果: 在完整的图片上用彩色圆圈标出监测点，并高亮显示识别结果。
"""

import cv2 as cv
import numpy as np
import time

def log(msg):
    """简易日志函数"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def is_color_yellow(bgr_color):
    """
    判断一个BGR颜色是否在定义的黄色范围内。
    """
    b, g, r = bgr_color
    # 定义一个宽容的黄色范围 (对应 RGB: R > 240, G > 160, B < 80)
    return (240 < r <= 255) and (160 < g < 200) and (b < 80)

def main():
    log("开始'精确坐标静态图片'最终验证...")

    # --- 用户提供的绝对坐标 (基于1920x1080全屏) ---
    tick_mark_abs_coords = {
        "Tick 1 (左一)": (808, 1016),
        "Tick 2 (左二)": (872, 952),
        "Tick 3 (中间)": (961, 929),
        "Tick 4 (右一)": (1048, 951)
    }
    
    # 关联测试图片和它们的正确结果
    image_files_map = {
        'templates/z1.png': "Tick 1 (左一)",
        'templates/z2.png': "Tick 2 (左二)",
        'templates/z3.png': "Tick 3 (中间)",
        'templates/z4.png': "Tick 4 (右一)"
    }

    for filepath, expected_tick in image_files_map.items():
        print("-" * 50)
        log(f"正在处理图片: {filepath}")
        
        img = cv.imread(filepath)
        if img is None:
            log(f"错误: 找不到测试图片 '{filepath}'")
            continue
        
        img_h, img_w = img.shape[:2]
        if not (img_w == 1920 and img_h == 1080):
            log(f"警告: 图片 '{filepath}' 的尺寸不是 1920x1080，坐标可能不准！")

        detected_location = "未检测到"
        
        # 遍历我们定义的4个分割点
        for name, (x, y) in tick_mark_abs_coords.items():
            try:
                # 直接在绝对坐标上获取颜色 (OpenCV是BGR格式)
                pixel_color_bgr = img[y, x]
                
                # 判断颜色是否为黄色
                if is_color_yellow(pixel_color_bgr):
                    detected_location = name
                    log(f"命中! 在 '{name}' 位置 { (x,y) } 检测到黄色。颜色(RGB): {pixel_color_bgr[::-1]}")
                    
                    # 用亮绿色高亮显示检测到的点
                    cv.circle(img, (x, y), 8, (0, 255, 0), -1) 
                    cv.circle(img, (x, y), 9, (255, 255, 255), 2)
                else:
                    # 用红色标出其他点
                    cv.circle(img, (x, y), 6, (0, 0, 255), 2)
            
            except IndexError:
                log(f"错误: 坐标 ({x}, {y}) 超出图片范围。")

        # 在图片上显示最终判断结果
        result_text = f"Detected: {detected_location} (Expected: {expected_tick})"
        color = (0, 255, 0) if detected_location == expected_tick else (0, 0, 255)
        cv.putText(img, result_text, (10, 30), cv.FONT_HERSHEY_SIMPLEX, 1, color, 2)

        window_name = f"Result for {filepath}"
        cv.namedWindow(window_name, cv.WINDOW_NORMAL)
        cv.imshow(window_name, img)

    print("-" * 50)
    log("所有图片处理完毕。按任意键关闭所有窗口。")
    cv.waitKey(0)
    cv.destroyAllWindows()
    log("测试结束。")

if __name__ == "__main__":
    main()