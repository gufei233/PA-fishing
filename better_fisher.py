# better_fisher.py
# -*- coding: utf-8 -*-

import time, threading, ctypes
from queue import Queue

import cv2 as cv
import numpy as np
import pyautogui as pg
import pygetwindow as gw
import win32gui, win32con
import tkinter as tk
import keyboard

# 载入外部配置
from bf_config import CFG

# ── 用 mss 接管 pyautogui.pixel（兼容 mss 9.x+） ───────────────────
try:
    import mss
    _sct = mss.mss()

    def _pixel_mss(x: int, y: int):
        """兼容所有 mss 版本；始终返回 (R,G,B)"""
        shot = _sct.grab({"left": x, "top": y, "width": 1, "height": 1})
        b, g, r, _ = shot.raw[:4]
        return (r, g, b)

    pg.pixel = _pixel_mss
    print("[INFO] 已启用 mss.grab(1×1) → pyautogui.pixel 加速 (mss 9.x)")
except Exception as e:
    print(f"[INFO] mss 加速不可用，继续用原生 pyautogui.pixel ({e})")
# ────────────────────────────────────────────────────────────────


# ---------------------- SendInput 双通道点击 ----------------------
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

# ---------------------- 连败计数 ----------------------
FAIL_STREAK = 0

def reset_fail_streak():
    global FAIL_STREAK
    FAIL_STREAK = 0

def inc_fail_streak():
    global FAIL_STREAK
    FAIL_STREAK += 1
    log(f"⚠️ 本轮失败，当前连续失败 {FAIL_STREAK}/{CFG.max_fail_streak}")
    return FAIL_STREAK >= CFG.max_fail_streak

# ---------------------- 悬浮窗日志 ----------------------
class Overlay:
    def __init__(self, font=None):
        if font is None:
            font = (CFG.overlay.font_name, CFG.overlay.font_size)
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
        if CFG.overlay.click_through: ex_style |= win32con.WS_EX_TRANSPARENT
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

# —— 色样本（来自配置） ——
YELLOW_SAMPLES       = [_hex_to_rgb(x) for x in CFG.colors.yellow_samples]
WHITE_SAMPLES        = [_hex_to_rgb(x) for x in CFG.colors.white_samples]
BANNER_YELLOWS       = [_hex_to_rgb(x) for x in CFG.colors.banner_yellows]
BUCKET_TOP_YELLOWS   = [_hex_to_rgb(x) for x in CFG.colors.bucket_top_yellows]
BUCKET_BOT_BEIGES    = [_hex_to_rgb(x) for x in CFG.colors.bucket_bot_beiges]

def is_color_yellow(rgb):
    if _near(rgb, YELLOW_SAMPLES, tol=CFG.colors.tol["yellow"]): return True
    h,s,v = _rgb2hsv(rgb); return (10 <= h <= 50) and (s >= 120) and (v >= 120)
def is_color_white(rgb):
    if _near(rgb, WHITE_SAMPLES, tol=CFG.colors.tol["white"]): return True
    r,g,b = rgb; return (r>=190 and g>=190 and b>=170) and (max(r,g,b)-min(r,g,b) <= 30)
def _is_banner_yellow(rgb):     return _near(rgb, BANNER_YELLOWS,     tol=CFG.colors.tol["banner"])
def is_bucket_top_yellow(rgb):  return _near(rgb, BUCKET_TOP_YELLOWS, tol=CFG.colors.tol["bucket_top"])
def is_bucket_bot_beige(rgb):   return _near(rgb, BUCKET_BOT_BEIGES,  tol=CFG.colors.tol["bucket_bot"])

# ---------------------- 判定工具 ----------------------
def get_tick_colors():
    try: return {i: pg.pixel(x,y) for i,(x,y) in CFG.coords.tick_coords.items()}
    except: return {1:(0,0,0),2:(0,0,0),3:(0,0,0),4:(0,0,0)}

def tension_gauge_visible_any():
    cs = get_tick_colors()
    return any(is_color_white(c) or is_color_yellow(c) for c in cs.values())

def tension_gauge_start_by_Z1():
    return is_color_yellow(pg.pixel(*CFG.coords.tick_coords[1]))

def banner_visible_once():
    try:
        c1 = pg.pixel(*CFG.coords.banner_coords[0])
        c2 = pg.pixel(*CFG.coords.banner_coords[1])
    except Exception:
        return False
    return _is_banner_yellow(c1) and _is_banner_yellow(c2)

def wait_banner_visible(timeout=None, stable=2):
    ok, t0 = 0, time.time()
    while True:
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        ok = ok+1 if banner_visible_once() else 0
        if ok >= stable: return True
        if timeout and time.time()-t0 > timeout: return False
        time.sleep(0.05)

def wait_banner_disappear(stable=3):
    miss = 0
    while True:
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        miss = miss+1 if not banner_visible_once() else 0
        if miss >= stable: return True
        time.sleep(0.05)

def bucket_visible_once():
    """鱼桶可见：顶部两黄、底部两米白"""
    try:
        t1 = pg.pixel(*CFG.coords.bucket_coords["top"][0])
        t2 = pg.pixel(*CFG.coords.bucket_coords["top"][1])
        b1 = pg.pixel(*CFG.coords.bucket_coords["bottom"][0])
        b2 = pg.pixel(*CFG.coords.bucket_coords["bottom"][1])
    except Exception:
        return False
    return is_bucket_top_yellow(t1) and is_bucket_top_yellow(t2) and is_bucket_bot_beige(b1) and is_bucket_bot_beige(b2)

def wait_bucket_visible(timeout=5.0, stable=2):
    ok, t0 = 0, time.time(); log("等待鱼桶出现…")
    while True:
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        ok = ok+1 if bucket_visible_once() else 0
        if ok >= stable: log("鱼桶已出现"); return True
        if timeout and time.time()-t0 > timeout: log("等待鱼桶出现超时"); return False
        time.sleep(0.05)

def wait_bucket_disappear(timeout=None, stable=3):
    miss = 0; log("鱼桶已出现，等待其消失（无超时）…")
    while True:
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        miss = miss+1 if not bucket_visible_once() else 0
        if miss >= stable: log("鱼桶消失 → 咬钩!"); return True
        time.sleep(0.05)

# ---------------------- 基础动作 ----------------------
def cast(wrect):
    focus_game()
    cx, cy = (wrect[0]+wrect[2]//2, wrect[1]+wrect[3]//2)
    pg.moveTo(cx, cy, duration=0.05)
    pg.mouseDown(button='left'); time.sleep(CFG.timings.cast_press_hold); pg.mouseUp(button='left')
    time.sleep(CFG.timings.cast_after_sleep)

def show_bucket(wrect, *, hold_ms=None, swipe_ratio=None, use_drag=None):
    """展示鱼桶动画：按下配置键并向左拖拽一段距离"""
    if hold_ms is None: hold_ms = CFG.timings.bucket_hold_ms
    if swipe_ratio is None: swipe_ratio = CFG.timings.bucket_swipe_ratio
    if use_drag is None: use_drag = CFG.timings.bucket_use_drag

    focus_game()
    L,T,W,H = wrect
    start_x = L + int(0.80*W)
    start_y = T + int(0.50*H)
    dx = -int(swipe_ratio * W)
    pg.moveTo(start_x, start_y, duration=0.05)
    keyboard.press(CFG.keys.show_bucket); time.sleep(0.10)
    dur = max(0.15, hold_ms/1000*0.6)
    if use_drag: pg.dragRel(dx, 0, duration=dur, button='left')
    else:        pg.moveRel(dx, 0, duration=dur)
    slept = 0.10 + dur
    if slept < hold_ms/1000: time.sleep(hold_ms/1000 - slept)
    if use_drag: pg.mouseUp(button='left')
    keyboard.release(CFG.keys.show_bucket)
    time.sleep(0.12)

def ensure_tension_by_clicks(wrect, press_hold=0.06, interval=1.0, timeout=None):
    cx, cy = (wrect[0] + wrect[2] // 2, wrect[1] + wrect[3] // 2)
    log("点按左键以触发拉力盘（Z1 变黄）…")
    start = time.time()
    while True:
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        pg.moveTo(cx, cy, duration=0.01)
        pg.mouseDown(button='left'); time.sleep(press_hold); pg.mouseUp(button='left')
        for _ in range(int(interval / 0.05)):
            if tension_gauge_start_by_Z1(): log("Z1 变黄 → 拉力盘出现"); return True
            if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
            time.sleep(0.05)
        if timeout and (time.time() - start > timeout):
            log("超时：多次点按仍未出现拉力盘"); return False

def collect_fish(win_rect, press_hold=0.08):
    cx, cy = (win_rect[0]+win_rect[2]//2, win_rect[1]+win_rect[3]//2)
    pg.moveTo(cx, cy, duration=0.01)
    pg.mouseDown(button='left'); time.sleep(press_hold); pg.mouseUp(button='left')
    time.sleep(0.15)

# ---------------------- 对中：Z2→停→Z3（含早退成功判定与Z1防卡死） ----------------------
def prime_to_Z2_then_Z3_with_anti_stall():
    def early_disappear_judgement(tag: str):
        log(f"{tag}途中拉力盘消失 → 等1秒判断是否上鱼")
        time.sleep(1.0)
        if banner_visible_once():
            log("拉力盘提前消失但检测到黄框 → 已上鱼")
            return "SUCCESS_EARLY"
        log("拉力盘提前消失且无黄框 → 空军")
        return False

    log("对中阶段：拉到 Z2 → 停 {:.1f} s → 拉到 Z3 …".format(CFG.timings.prime_pause_sec))
    # → Z2
    mouse_down()
    z1_stuck_since = None
    try:
        while True:
            if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
            if is_color_yellow(pg.pixel(*CFG.coords.tick_coords[2])): break
            # 收线卡死保护：Z1黄持续>阈值，松一段时间再继续
            if is_color_yellow(pg.pixel(*CFG.coords.tick_coords[1])):
                z1_stuck_since = z1_stuck_since or time.time()
                if time.time() - z1_stuck_since > CFG.timings.z1_stuck_threshold:
                    log(f"Z1 卡死保护 → 松{CFG.timings.z1_stuck_release_sec:.1f}s继续")
                    mouse_up(); time.sleep(CFG.timings.z1_stuck_release_sec); mouse_down()
                    z1_stuck_since = time.time()
            else:
                z1_stuck_since = None
            if not tension_gauge_visible_any():
                mouse_up()
                return early_disappear_judgement("对中到Z2")
            time.sleep(0.02)
    finally:
        mouse_up()
    time.sleep(CFG.timings.prime_pause_sec)

    # → Z3
    mouse_down()
    try:
        while True:
            if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
            if is_color_yellow(pg.pixel(*CFG.coords.tick_coords[3])): break
            if not tension_gauge_visible_any():
                mouse_up()
                return early_disappear_judgement("对中到Z3")
            time.sleep(0.02)
    finally:
        mouse_up()
    log("已到 Z3，松线进入循环")
    return True

# ---------------------- 分阶段四点状态机（>10s为Z3-固定节律） ----------------------
def reel_with_timer(tension_start_ts):
    """
    Phase A（0-10 s） : Z2 ↔ Z3 状态机
    Phase B（>阈值且此刻 Z2=黄） : 固定节奏
        循环：
            mouse_down  → 拉到 Z3 黄
            mouse_up    → 松线 固定秒
    """
    if not tension_gauge_visible_any():
        return True

    state  = 'RELEASING'
    phaseB = False
    first_B_cycle = True
    log(f"进入循环：Phase A = Z2↔Z3；满足(>{CFG.timings.phaseB_switch_elapsed:.1f} s & Z2黄) → Phase B = Z3-{CFG.timings.phaseB_release_sec:.1f} s 节拍")

    while True:
        # ------------ 公共退出判定 ------------
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        if not tension_gauge_visible_any():
            log("拉力盘消失（由外层判断成功 / 空军）"); return True

        # 读取 4 点颜色 & 时间
        c1 = pg.pixel(*CFG.coords.tick_coords[1])
        c2 = pg.pixel(*CFG.coords.tick_coords[2])
        c3 = pg.pixel(*CFG.coords.tick_coords[3])
        c4 = pg.pixel(*CFG.coords.tick_coords[4])
        elapsed = time.time() - tension_start_ts

        # ------------ Phase B : 固定节奏 ------------
        if phaseB:
            # 第一次进入 B：先拉到 Z3；之后循环：拉到 Z3 → 松 固定秒
            if first_B_cycle:
                first_B_cycle = False
            else:
                time.sleep(CFG.timings.phaseB_release_sec)

            # 收线到 Z3
            mouse_down()
            try:
                while not is_color_yellow(pg.pixel(*CFG.coords.tick_coords[3])):
                    if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
                    if not tension_gauge_visible_any(): return True
                    # 收线 Z1 卡死保护
                    if is_color_yellow(pg.pixel(*CFG.coords.tick_coords[1])):
                        mouse_up(); time.sleep(CFG.timings.z1_stuck_release_sec); mouse_down()
                    # 收线 Z4 越界（保险）
                    if is_color_yellow(pg.pixel(*CFG.coords.tick_coords[4])):
                        break
                    time.sleep(0.02)
            finally:
                mouse_up()
            continue  # B 阶段固定节拍循环

        # ------------ Phase A : 原四点状态机 ------------
        # 满足 (>阈值 & Z2 黄) → 立即切到 Phase B
        if (not phaseB) and (elapsed > CFG.timings.phaseB_switch_elapsed) and is_color_yellow(c2):
            log("满足条件 → 进入 Phase B（Z3-固定节拍）")
            phaseB = True
            first_B_cycle = True
            continue

        # ---------- 以下为 Phase A ----------
        if state == 'RELEASING':
            # 放线 Z1 救援
            if is_color_yellow(c1):
                mouse_down()
                while not is_color_yellow(pg.pixel(*CFG.coords.tick_coords[3])):
                    if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
                    if not tension_gauge_visible_any(): return True
                    time.sleep(0.02)
                mouse_up(); continue
            # 正常放到 Z2 → 收线
            if is_color_yellow(c2):
                mouse_down(); state = 'REELING'

        else:  # REELING
            # 收线 Z1 卡死
            if is_color_yellow(c1):
                mouse_up(); time.sleep(CFG.timings.z1_stuck_release_sec); mouse_down(); continue
            # Z3 → 放线
            if is_color_yellow(c3):
                mouse_up(); state = 'RELEASING'
            # Z4 → 刹车放到 Z2
            elif is_color_yellow(c4):
                mouse_up()
                while not is_color_yellow(pg.pixel(*CFG.coords.tick_coords[2])):
                    if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
                    if not tension_gauge_visible_any(): return True
                    time.sleep(0.02)
                mouse_down(); state = 'REELING'

        time.sleep(0.02)

# ---------------------- 单轮流程 ----------------------
def fish_one_round(win_rect):
    """单轮：抛竿 → 调桶 → (≤配置秒 等咬钩) → 后续流程"""
    # 1) 抛竿
    cast(win_rect); log("抛竿完成")

    # 2) 调桶
    show_bucket(win_rect,
                hold_ms=CFG.timings.bucket_hold_ms,
                swipe_ratio=CFG.timings.bucket_swipe_ratio,
                use_drag=CFG.timings.bucket_use_drag)
    log("尝试显示鱼桶…")
    if not wait_bucket_visible(timeout=CFG.timings.wait_bucket_visible_timeout,
                               stable=CFG.timings.wait_bucket_visible_stable):
        log("首次调桶未见到鱼桶 → 再试一次")
        show_bucket(win_rect,
                    hold_ms=CFG.timings.bucket_hold_ms,
                    swipe_ratio=CFG.timings.bucket_swipe_ratio,
                    use_drag=CFG.timings.bucket_use_drag)
        if not wait_bucket_visible(timeout=CFG.timings.wait_bucket_visible_timeout,
                                   stable=CFG.timings.wait_bucket_visible_stable):
            log("两次调桶都未见到鱼桶 → 本轮失败")
            return False

    # 3) 最多等配置的秒数咬钩
    log(f"开始计时等待咬钩（最长 {CFG.timings.wait_bite_seconds:.0f} 秒）…")
    start_wait = time.time()
    while True:
        if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
        if bucket_visible_once():
            pass  # 仍在等待
        else:
            log("鱼桶消失 → 咬钩!")
            break
        if time.time() - start_wait >= CFG.timings.wait_bite_seconds:
            log(f"⌛ 等待 {CFG.timings.wait_bite_seconds:.0f} 秒仍未咬钩 → 判失败，按 {CFG.keys.abort_wait.upper()} 收杆")
            keyboard.press_and_release(CFG.keys.abort_wait)
            # 等桶消失干净再返回失败
            wait_bucket_disappear(timeout=None, stable=CFG.timings.wait_bucket_disappear_stable)
            return False
        time.sleep(0.05)

    if not ensure_tension_by_clicks(
            win_rect,
            press_hold=CFG.timings.ensure_press_hold,
            interval=CFG.timings.ensure_interval,
            timeout=CFG.timings.ensure_timeout):
        return False
    tension_start_ts = time.time()

    prime_res = prime_to_Z2_then_Z3_with_anti_stall()
    if prime_res == "SUCCESS_EARLY":
        pass
    elif not prime_res:
        return False

    if prime_res != "SUCCESS_EARLY":
        if not reel_with_timer(tension_start_ts):
            return False

    time.sleep(CFG.timings.post_tension_check_delay)
    if not banner_visible_once():
        log("拉力盘消失后未见提示框 → 空军")
        return False
    wait_banner_visible(timeout=CFG.timings.banner_wait_timeout, stable=CFG.timings.banner_wait_stable)
    log("检测到黄色提示框 → 开始收鱼")

    for _ in range(CFG.timings.collect_cycles_max):
        if not banner_visible_once(): break
        collect_fish(win_rect, press_hold=CFG.timings.collect_press_hold)
        time.sleep(CFG.timings.collect_cycle_sleep)
    if banner_visible_once():
        log("⚠️ 提示框未消失，收鱼失败")
        return False

    log("收鱼成功")
    return True

# ---------------------- 主程序 ----------------------
def main():
    try:
        win_rect = get_win_rect()
        log(f"窗口：{win_rect}  3 秒后开始；按 '{CFG.keys.exit_key}' 退出")
        for i in (3,2,1):
            if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
            log(str(i)); time.sleep(1.0)

        total=succ=0
        while True:
            if keyboard.is_pressed(CFG.keys.exit_key): raise KeyboardInterrupt
            res = fish_one_round(win_rect)
            total += 1
            if res:
                succ += 1
                reset_fail_streak()
                log(f"本次成功 | 累计 {succ}/{total} = {succ/total*100:.1f}%")
            else:
                # 本轮失败
                if inc_fail_streak():
                    log(f"连续 {CFG.max_fail_streak} 次失败 → 退出脚本")
                    break
                log(f"本次失败 | 累计 {succ}/{total} = {succ/total*100:.1f}%")

            # 成功 X 条后自动停止
            if succ >= CFG.timings.stop_after_n_success:
                log(f"已成功 {succ} 条，达到阈值 {CFG.timings.stop_after_n_success} → 停止脚本")
                break

            if total % CFG.timings.recalc_every == 0:
                win_rect = get_win_rect()
    except KeyboardInterrupt:
        mouse_up(); log(f"用户按 '{CFG.keys.exit_key}' 或 Ctrl+C 退出")
    except Exception as e:
        mouse_up(); log(f"主程序发生错误: {e}"); raise

if __name__ == "__main__":
    main()
