# -*- coding: utf-8 -*-
"""
PA Fishing 
- 出现拉力盘后：拉到Z2→停0.5s→拉到Z3（松）→进入收线循环
- 10秒计时分阶段：
  * Phase A（0~10s）：Z2↔Z3循环（放线只看Z1/Z2；收线只看Z3/Z4）
  * Phase B（>10s）：不再检测Z2；放线触达Z2即“拉到Z3→停0.5s→松”形成Z3-0.5s节律
- 全程Z1防卡死：收线Z1黄→松0.5s继续；放线Z1黄→立即改为收线直达Z3
- 成功判定修复：必须“拉力盘消失 且 提示框出现”；否则为空军
- 收鱼：循环“按住式”点击直至提示框消失（最多10次）
"""

import time, threading, ctypes
from dataclasses import dataclass
from queue import Queue

import cv2 as cv
import numpy as np
import pyautogui as pg
import pygetwindow as gw
import win32gui, win32con
import tkinter as tk
import keyboard

# ---------------------- 鼠标控制（双保险） ----------------------
SendInput = ctypes.windll.user32.SendInput
PUL = ctypes.POINTER(ctypes.c_ulong)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL))
class INPUT(ctypes.Structure):
    _fields_ = (("type", ctypes.c_ulong), ("mi", MOUSEINPUT))
def _mouse_event(flags):
    ii = INPUT(); ii.type = 0
    ii.mi = MOUSEINPUT(0,0,0,flags,0, ctypes.cast(ctypes.pointer(ctypes.c_ulong(0)),PUL))
    SendInput(1, ctypes.byref(ii), ctypes.sizeof(ii))
def mouse_down():
    try: pg.mouseDown(button='left')
    except: pass
    _mouse_event(0x0002)
def mouse_up():
    try: pg.mouseUp(button='left')
    except: pass
    _mouse_event(0x0004)

# ---------------------- 配置 ----------------------
@dataclass
class Cfg:
    title = "猛兽派对"
    exit_key = 'q'
    # 四个张力盘坐标（1920×1080）
    tick_coords = {
        1: (808, 1016),  # Z1
        2: (872,  952),  # Z2
        3: (961,  929),  # Z3
        4: (1048, 951),  # Z4
    }
    # 鱼桶可见判定：顶部两黄 + 底部两米白
    bucket_coords = {
        "top":    [(1479, 336), (1768, 337)],
        "bottom": [(1449, 878), (1814, 880)],
    }
    # 鱼桶将满（三白像素）
    bucket_full_coords = [(1679,820), (1677,824), (1680,824)]
    # 成功黄色提示框
    banner_coords = [(1200, 65), (1210, 153)]
    recalc_every = 12
    overlay_click_through = True
CFG = Cfg()

# ---------------------- 悬浮窗日志 ----------------------
class Overlay:
    def __init__(self, font=("Consolas", 11)):
        self.font, self.queue = font, Queue()
        threading.Thread(target=self._run, daemon=True).start()
    def _run(self):
        root = tk.Tk()
        root.overrideredirect(True); root.attributes("-topmost", True); root.config(bg="black")
        txt = tk.Text(root, width=66, height=18, bg="black", fg="white",
                      insertbackground="white", font=self.font, highlightthickness=0, border=0)
        txt.pack(anchor="sw", padx=6, pady=6); txt.configure(state="disabled")
        hwnd = root.winfo_id()
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED
        if CFG.overlay_click_through: ex_style |= win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
        win32gui.SetLayeredWindowAttributes(hwnd, 0, 255, win32con.LWA_COLORKEY)
        def tick():
            while not self.queue.empty():
                cmd, data = self.queue.get()
                if cmd == "log":
                    txt.configure(state="normal"); txt.insert("end", data); txt.see(tk.END); txt.configure(state="disabled")
                elif cmd == "move":
                    L,T,W,H = data; root.geometry(f"+{L+10}+{T+H-360}")
            root.after(80, tick)
        tick(); root.mainloop()
    def move_to_window(self, rect): self.queue.put(("move", rect))
    def log(self, msg):
        ts = time.strftime("%H:%M:%S"); line = f"[{ts}] {msg}\n"; print(line, end="")
        self.queue.put(("log", line))
LOGGER = Overlay()
def log(msg): LOGGER.log(msg)

# ---------------------- 窗口与聚焦 ----------------------
def focus_game():
    if wins := gw.getWindowsWithTitle(CFG.title):
        try: wins[0].activate()
        except: pass
        time.sleep(0.05)
def get_win_rect():
    wins = gw.getWindowsWithTitle(CFG.title)
    if not wins: raise RuntimeError("找不到游戏窗口")
    win = wins[0]; rect = (win.left, win.top, win.width, win.height)
    LOGGER.move_to_window(rect); return rect

# ---------------------- 颜色工具 ----------------------
def _hex_to_rgb(hs: str):
    hs = hs.strip().lstrip('#'); return (int(hs[0:2],16), int(hs[2:4],16), int(hs[4:6],16))
def _near(rgb, samples, tol=90):
    r,g,b = rgb
    for sr,sg,sb in samples:
        if abs(r-sr)+abs(g-sg)+abs(b-sb) <= tol: return True
    return False
def _rgb2hsv(rgb):
    arr = np.uint8([[list(rgb)]])
    hsv = cv.cvtColor(arr, cv.COLOR_RGB2HSV)[0,0]
    return tuple(int(x) for x in hsv)

# —— 颜色样本 ——
YELLOW_SAMPLES       = [_hex_to_rgb(x) for x in ("#ffaa29","#ffb63f","#ffaa2b")]     # 张力盘指针黄
WHITE_SAMPLES        = [_hex_to_rgb(x) for x in ("#dee1c5","#dee1cd","#dee2ca","#f7f3de","#f7f4e4")]
BANNER_YELLOWS       = [_hex_to_rgb(x) for x in ("#ffe84f", "#ffe952")]              # 上鱼提示框黄
BUCKET_TOP_YELLOWS   = [_hex_to_rgb(x) for x in ("#fbd560","#fcd35f","#fbd35e","#f9d460")]
BUCKET_BOT_BEIGES    = [_hex_to_rgb(x) for x in ("#f4e3bb","#f3e3bb","#f2e2ba","#f3e2ba")]
BUCKET_FULL_WHITES   = [_hex_to_rgb(x) for x in ("#fbfafa", "#fafafa", "#fbfbfa")]

def is_color_yellow(rgb):
    if _near(rgb, YELLOW_SAMPLES, tol=90): return True
    h,s,v = _rgb2hsv(rgb); return (10 <= h <= 50) and (s >= 120) and (v >= 120)
def is_color_white(rgb):
    if _near(rgb, WHITE_SAMPLES, tol=70): return True
    r,g,b = rgb; return (r>=190 and g>=190 and b>=170) and (max(r,g,b)-min(r,g,b) <= 30)
def _is_banner_yellow(rgb):     return _near(rgb, BANNER_YELLOWS,     tol=80)
def is_bucket_top_yellow(rgb):  return _near(rgb, BUCKET_TOP_YELLOWS, tol=85)
def is_bucket_bot_beige(rgb):   return _near(rgb, BUCKET_BOT_BEIGES,  tol=85)
def _is_bucket_full_white(rgb): return _near(rgb, BUCKET_FULL_WHITES, tol=80)

# ---------------------- 基础像素读数/判定 ----------------------
def get_tick_colors():
    try: return {i: pg.pixel(x,y) for i,(x,y) in CFG.tick_coords.items()}
    except: return {1:(0,0,0),2:(0,0,0),3:(0,0,0),4:(0,0,0)}

def tension_gauge_visible_any():
    cs = get_tick_colors()
    return any(is_color_white(c) or is_color_yellow(c) for c in cs.values())

def tension_gauge_start_by_Z1():
    return is_color_yellow(pg.pixel(*CFG.tick_coords[1]))

# ---- 成功提示框 ----
def banner_visible_once():
    try:
        c1 = pg.pixel(*CFG.banner_coords[0])
        c2 = pg.pixel(*CFG.banner_coords[1])
    except Exception:
        return False
    return _is_banner_yellow(c1) and _is_banner_yellow(c2)

def wait_banner_visible(timeout=3.0, stable=2):
    ok, t0 = 0, time.time()
    while True:
        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
        ok = ok+1 if banner_visible_once() else 0
        if ok >= stable: return True
        if timeout and time.time()-t0 > timeout: return False
        time.sleep(0.05)

def wait_banner_disappear(stable=3):
    miss = 0
    while True:
        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
        miss = miss+1 if not banner_visible_once() else 0
        if miss >= stable: return True
        time.sleep(0.05)

# ---- 鱼桶（可见/满） ----
def bucket_visible_once():
    try:
        t1 = pg.pixel(*CFG.bucket_coords["top"][0])
        t2 = pg.pixel(*CFG.bucket_coords["top"][1])
        b1 = pg.pixel(*CFG.bucket_coords["bottom"][0])
        b2 = pg.pixel(*CFG.bucket_coords["bottom"][1])
    except Exception:
        return False
    return is_bucket_top_yellow(t1) and is_bucket_top_yellow(t2) and is_bucket_bot_beige(b1) and is_bucket_bot_beige(b2)

def wait_bucket_visible(timeout=5.0, stable=2):
    ok, t0 = 0, time.time(); log("等待鱼桶出现…")
    while True:
        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
        ok = ok+1 if bucket_visible_once() else 0
        if ok >= stable: log("鱼桶已出现"); return True
        if timeout and time.time()-t0 > timeout: log("等待鱼桶出现超时"); return False
        time.sleep(0.05)

def wait_bucket_disappear(timeout=None, stable=3):
    miss = 0; log("鱼桶已出现，等待其消失（无超时）…")
    while True:
        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
        miss = miss+1 if not bucket_visible_once() else 0
        if miss >= stable: log("鱼桶消失 → 咬钩!"); return True
        time.sleep(0.05)

def bucket_full_once():
    try:
        c1 = pg.pixel(*CFG.bucket_full_coords[0])
        c2 = pg.pixel(*CFG.bucket_full_coords[1])
        c3 = pg.pixel(*CFG.bucket_full_coords[2])
    except Exception:
        return False
    ok = _is_bucket_full_white(c1) and _is_bucket_full_white(c2) and _is_bucket_full_white(c3)
    if ok: log(f"检测到桶满 RGB:{c1} {c2} {c3}")
    return ok

# ---------------------- 基础动作 ----------------------
def cast(wrect):
    focus_game()
    cx, cy = (wrect[0]+wrect[2]//2, wrect[1]+wrect[3]//2)
    pg.moveTo(cx, cy, duration=0.05)
    pg.mouseDown(button='left'); time.sleep(0.06); pg.mouseUp(button='left')
    time.sleep(1.5)

def show_bucket(wrect, *, hold_ms=500, swipe_ratio=0.30, use_drag=True):
    focus_game()
    L,T,W,H = wrect
    start_x = L + int(0.80*W)
    start_y = T + int(0.50*H)
    dx = -int(swipe_ratio * W)
    pg.moveTo(start_x, start_y, duration=0.05)
    keyboard.press('c'); time.sleep(0.10)
    dur = max(0.15, hold_ms/1000*0.6)
    if use_drag: pg.dragRel(dx, 0, duration=dur, button='left')
    else:        pg.moveRel(dx, 0, duration=dur)
    slept = 0.10 + dur
    if slept < hold_ms/1000: time.sleep(hold_ms/1000 - slept)
    if use_drag: pg.mouseUp(button='left')
    keyboard.release('c')
    time.sleep(0.12)

def ensure_tension_by_clicks(wrect, press_hold=0.06, interval=1.0, timeout=None):
    cx, cy = (wrect[0] + wrect[2] // 2, wrect[1] + wrect[3] // 2)
    log("点按左键以触发拉力盘（Z1 变黄）…")
    start = time.time()
    while True:
        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
        pg.moveTo(cx, cy, duration=0.01)
        pg.mouseDown(button='left'); time.sleep(press_hold); pg.mouseUp(button='left')
        for _ in range(int(interval / 0.05)):
            if tension_gauge_start_by_Z1(): log("Z1 变黄 → 拉力盘出现"); return True
            if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
            time.sleep(0.05)
        if timeout and (time.time() - start > timeout):
            log("超时：多次点按仍未出现拉力盘"); return False

def collect_fish(win_rect, press_hold=0.08):
    cx, cy = (win_rect[0]+win_rect[2]//2, win_rect[1]+win_rect[3]//2)
    pg.moveTo(cx, cy, duration=0.01)
    pg.mouseDown(button='left'); time.sleep(press_hold); pg.mouseUp(button='left')
    time.sleep(0.15)

# ---------------------- 对中：出现拉力盘后先 Z2→停0.5→Z3 ----------------------
def prime_to_Z2_then_Z3_with_anti_stall():
    log("对中阶段：拉到 Z2 → 停 0.5 s → 拉到 Z3 …")
    # → Z2
    mouse_down()
    z1_stuck_since = None
    try:
        while True:
            if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
            if is_color_yellow(pg.pixel(*CFG.tick_coords[2])): break
            # 收线卡死保护（Z1黄持续>0.7s）
            if is_color_yellow(pg.pixel(*CFG.tick_coords[1])):
                z1_stuck_since = z1_stuck_since or time.time()
                if time.time() - z1_stuck_since > 0.7:
                    log("Z1 卡死保护 → 松0.5s继续")
                    mouse_up(); time.sleep(0.5); mouse_down()
                    z1_stuck_since = time.time()
            else:
                z1_stuck_since = None
            if not tension_gauge_visible_any():
                log("对中到Z2途中拉力盘消失")
                time.sleep(1.0) 
                if banner_visible_once(): 
                 log("拉力盘提前消失但检测到黄框 → 已上鱼")
                 return "SUCCESS_EARLY"
                else:
                 log("拉力盘提前消失且无黄框 → 判空军")
                 return False
            time.sleep(0.02)
    finally:
        mouse_up()
    time.sleep(0.5)

    # → Z3
    mouse_down()
    try:
        while True:
            if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
            if is_color_yellow(pg.pixel(*CFG.tick_coords[3])): break
            if not tension_gauge_visible_any():
                log("对中到Z3途中拉力盘消失")
                time.sleep(1.0) 
                if banner_visible_once(): 
                 log("拉力盘提前消失但检测到黄框 → 已上鱼")
                 return "SUCCESS_EARLY"
                else:
                 log("拉力盘提前消失且无黄框 → 判空军")
                 return False
            time.sleep(0.02)
    finally:
        mouse_up()
    log("已到 Z3，松线进入循环")
    return True

# ---------------------- 分阶段四点状态机（带10s计时） ----------------------
def reel_with_timer(tension_start_ts):
    """
    返回值：
      True  -> 拉力盘消失（可能成功也可能空军，由外层结合提示框判断）
      False -> 过程提前失败（例如异常/退出）
    """
    if not tension_gauge_visible_any():
        return True

    state = 'RELEASING'  # 初始从Z3松线开始
    log("进入循环：Phase A（0~10s）为 Z2↔Z3；Phase B（>10s）为 Z3-0.5s 节律")

    while True:
        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
        if not tension_gauge_visible_any():
            log("拉力盘消失（由外层判断是否成功/空军）"); return True

        elapsed = time.time() - tension_start_ts
        phaseA = (elapsed <= 10.0)

        c1 = pg.pixel(*CFG.tick_coords[1])
        c2 = pg.pixel(*CFG.tick_coords[2])
        c3 = pg.pixel(*CFG.tick_coords[3])
        c4 = pg.pixel(*CFG.tick_coords[4])

        if state == 'RELEASING':
            # 放线时Z1防卡死：立刻救援直到Z3
            if is_color_yellow(c1):
                log("Z1=黄（放线救援）→ 立刻收到 Z3")
                mouse_down()
                try:
                    while not is_color_yellow(pg.pixel(*CFG.tick_coords[3])):
                        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
                        if not tension_gauge_visible_any(): return True
                        time.sleep(0.02)
                finally:
                    mouse_up()
                continue

            if phaseA:
                # Phase A：标准Z2触发收线
                if is_color_yellow(c2):
                    log("Z2=黄 → 切【收线】"); state='REELING'; mouse_down()
            else:
                # Phase B：不再检测Z2；触达Z2就“拉到Z3→停0.5→松”，保持Z3节律
                if is_color_yellow(c2):
                    log("Phase B：Z2 命中 → 拉到Z3→停0.5→松")
                    mouse_down()
                    try:
                        while not is_color_yellow(pg.pixel(*CFG.tick_coords[3])):
                            if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
                            if not tension_gauge_visible_any(): return True
                            time.sleep(0.02)
                    finally:
                        mouse_up()
                    time.sleep(0.5)
                    # 继续放线等待下一次节律触发
        else:
            # 收线时Z1防卡死：暂停0.5s再继续
            if is_color_yellow(c1):
                log("Z1=黄（收线卡死保护）→ 暂停0.5s继续")
                mouse_up(); time.sleep(0.5); mouse_down(); time.sleep(0.02)
                continue

            if is_color_yellow(c3):
                log("Z3=黄 → 切【放线】"); state='RELEASING'; mouse_up()
            elif is_color_yellow(c4):
                log("Z4=黄（越界）→ 放线到 Z2")
                mouse_up()
                while not is_color_yellow(pg.pixel(*CFG.tick_coords[2])):
                    if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
                    if not tension_gauge_visible_any(): return True
                    time.sleep(0.02)
                if phaseA:
                    log("到 Z2 → 继续【收线】"); state='REELING'; mouse_down()
                else:
                    log("Phase B：Z2 → 拉到Z3→停0.5→松")
                    mouse_down()
                    while not is_color_yellow(pg.pixel(*CFG.tick_coords[3])):
                        if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
                        if not tension_gauge_visible_any(): return True
                        time.sleep(0.02)
                    mouse_up(); time.sleep(0.5)

        time.sleep(0.02)

# ---------------------- 单轮流程 ----------------------
def fish_one_round(win_rect):
    # 1) 抛竿
    cast(win_rect); log("抛竿完成")

    # 2) 调桶
    show_bucket(win_rect); log("尝试显示鱼桶…")
    if not wait_bucket_visible(timeout=2.0, stable=2):
        log("首次调桶未见到鱼桶 → 再试一次")
        show_bucket(win_rect)
        if not wait_bucket_visible(timeout=2.0, stable=2):
            log("两次调桶都未见到鱼桶 → 放弃本轮"); return False

    # 2.1) 出现就检测“将满”
    if bucket_full_once():
        log("检测到鱼桶已满 → 程序结束")
        return 'FULL'

    # 3) 等桶消失（咬钩）
    wait_bucket_disappear(stable=3)

    # 4) 触发拉力盘（Z1变黄）
    if not ensure_tension_by_clicks(win_rect, timeout=6.0, interval=1.0):
        return False
    tension_start_ts = time.time()

    # 5) 对中：Z2→停0.5→Z3
    prime_res = prime_to_Z2_then_Z3_with_anti_stall()
    if prime_res == "SUCCESS_EARLY":
     pass
    elif not prime_res:
     return False

    # 6) 分阶段收线（直到拉力盘消失）
    if not reel_with_timer(tension_start_ts):
        return False

    # 7) 成功判定：拉力盘已消失 → 必须出现黄色提示框，否则为空军
    time.sleep(1.0)
    if not banner_visible_once():
        log("拉力盘消失1秒未出现提示框 → 空军")
        return False

    # 8) 收鱼：循环点击直到提示框消失（最多10次）
    wait_banner_visible(timeout=2.0, stable=2)
    log("检测到黄色提示框 → 开始收鱼")
    for _ in range(10):
        if not banner_visible_once(): break
        collect_fish(win_rect, press_hold=0.08)
        time.sleep(0.6)
    if banner_visible_once():
        log("⚠️ 多次点击仍未收鱼成功，请检查提示框坐标/阈值")
        return False
    log("提示框已消失 → 收鱼完成")
    return True

# ---------------------- 主程序 ----------------------
def main():
    try:
        win_rect = get_win_rect()
        log(f"窗口：{win_rect}  3 秒后开始；按 '{CFG.exit_key}' 退出")
        for i in (3,2,1):
            if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
            log(str(i)); time.sleep(1.0)

        total=succ=0
        while True:
            if keyboard.is_pressed(CFG.exit_key): raise KeyboardInterrupt
            res = fish_one_round(win_rect)
            if res == 'FULL':
                log("鱼桶满 → 结束全部钓鱼")
                break
            total += 1; succ += 1 if res else 0
            log(f"本次{'成功' if res else '空军'} | 累计 {succ}/{total} = {succ/total*100:.1f}%")
            if total % CFG.recalc_every == 0:
                win_rect = get_win_rect()
    except KeyboardInterrupt:
        mouse_up(); log(f"用户按 '{CFG.exit_key}' 或 Ctrl+C 退出")
    except Exception as e:
        mouse_up(); log(f"主程序发生错误: {e}"); raise

if __name__ == "__main__":
    main()
