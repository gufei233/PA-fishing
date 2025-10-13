# -*- coding: utf-8 -*-
import time, threading, ctypes, re, os
from pathlib import Path
from typing import Dict, Tuple, List, Sequence
from queue import Queue

import cv2 as cv
import numpy as np
import pyautogui as pg
import pygetwindow as gw
import win32gui, win32con
import tkinter as tk
import tkinter.font as tkfont
import keyboard

# 载入外部配置
from bf_config import CFG

# ───────────────────────────────────────────────────────────────────────
# 【整合自 mark_points.py 的基准与绘制配置】（以 1920×1080 为基准）
# 说明：这里保留独立的“基准点”，用于“按分辨率比例换算”，不会受运行时 CFG 变更影响。
#      若你希望以后更改基准，只需改这里即可（不必碰钓鱼逻辑）。
MP_BASE_SIZE = (1920, 1080)  # (W0, H0)
MP_TICK_BASE = {             # 张力盘四点（基准）
    1: (808, 1016), 2: (872, 952), 3: (961, 929), 4: (1048, 951),
}
MP_BUCKET_BASE = {           # 鱼桶：上 2 黄、下 2 米白（基准）
    "top":    [(1479, 336), (1768, 337)],
    "bottom": [(1509, 848), (1734, 848)],
}
MP_BANNER_BASE = [(1200, 65), (1210, 153)]  # 黄框两点（基准）

# 绘制参数（仅用于生成校验图）
MK_RADIUS   = 10
MK_THICK    = 2
MK_FONT     = cv.FONT_HERSHEY_SIMPLEX
MK_FSCALE   = 0.6
MK_FTHICK   = 2
MK_COLOR    = (0, 0, 255)  # BGR 红色

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

# ---------------------- 运行时状态 ----------------------
class RestartRound(Exception):
    """用于从任意深度的循环里立即跳回主循环，并从抛竿重新开始。"""
    pass

PAUSE_FLAG      = threading.Event()   # True=暂停
RESUME_RESTART  = threading.Event()   # 恢复后是否强制重开一轮（每次恢复都置 True）
EXIT_FLAG       = threading.Event()   # True=请求退出
PAUSE_REASON    = None                # 'manual' | 'bucket_full' | 'fail_streak' | None

# 连败/统计计数
FAIL_STREAK = 0           # 连续失败次数（恢复后清零）
SUCC = 0                  # 全局成功次数（不随暂停清零）
TOTAL = 0                 # 全局总轮数
BUCKET_SUCC = 0           # “本桶计数”——只用于达到 stop_after_n_success 的自动暂停

def on_exit_hotkey():
    """全局热键：立即请求退出（暂停中也生效）"""
    EXIT_FLAG.set()

def reset_fail_streak():
    global FAIL_STREAK
    FAIL_STREAK = 0

def inc_fail_streak():
    global FAIL_STREAK
    FAIL_STREAK += 1
    log(f"⚠️ 本轮失败，当前连续失败 {FAIL_STREAK}/{CFG.max_fail_streak}")
    return FAIL_STREAK >= CFG.max_fail_streak

# ───────────────── 悬浮窗 Overlay ─────────────────
class Overlay:
    """左下角悬浮窗，黑底白字，不抢焦点，可自动上移防止超出屏幕。
       支持全局 Alpha 半透明 + 颜色键（黑色背景完全穿透，文字半透明）。"""
    def __init__(self):
        self.queue = Queue()
        self.visible = True
        threading.Thread(target=self._run, daemon=True).start()

    # ---------- 供外部调用 ----------
    def move_to_window(self, rect): self.queue.put(("move", rect))
    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        print(line, end="")               # 终端立即输出
        self.queue.put(("log", line))     # UI 线程异步刷新
    def toggle_visible(self):
        self.visible = not self.visible
        self.queue.put(("toggle", self.visible))

    # ---------- UI 线程 ----------
    def _run(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        COLKEY = "#ff00ff"               # 亮品红
        self.root.config(bg=COLKEY)

        self.txt = tk.Text(self.root, width=66, height=18,
                           bg=COLKEY, fg="white",
                           insertbackground="white",
                           highlightthickness=0, border=0)
        self.txt.pack(anchor="sw", padx=6, pady=6)
        self.txt.configure(state="disabled")

        # === 透明 / 颜色键 / 点击穿透 =====================
        hwnd = self.root.winfo_id()
        ex  = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex  |= win32con.WS_EX_LAYERED
        if CFG.overlay.click_through:
            ex |= win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)

        import win32api
        colref = win32api.RGB(255, 0, 255)
        win32gui.SetLayeredWindowAttributes(
            hwnd, colref, 0, win32con.LWA_COLORKEY
        )
        self.root.attributes("-alpha", max(0, min(CFG.overlay.alpha, 255)) / 255)

        def tick():
            while not self.queue.empty():
                cmd, data = self.queue.get()
                if cmd == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", data)
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                    self._ensure_visible()
                elif cmd == "move":
                    L, T, W, H = data
                    self._reposition(L, T, W, H)
                elif cmd == "toggle":
                    self.root.deiconify() if data else self.root.withdraw()
            self.root.after(15, tick)
        tick()
        self.root.mainloop()

    # ---------- 可见性 & 定位 ----------
    def _reposition(self, L, T, W, H):
        """初次定位到游戏窗口左下角上方 10 px，且不超屏"""
        self.root.update_idletasks()
        h = self.root.winfo_height()
        scr_h = self.root.winfo_screenheight()
        new_x = L + 10
        new_y = min(T + H - h - 10, scr_h - h - 10)
        self.root.geometry(f"+{new_x}+{new_y}")

    def _ensure_visible(self):
        """写入新行后，如窗口底端超出屏幕则整体上移"""
        self.root.update_idletasks()
        scr_h = self.root.winfo_screenheight()
        y = self.root.winfo_y()
        h = self.root.winfo_height()
        if y + h + 5 > scr_h:              # 留 5 px 缓冲
            new_y = max(0, scr_h - h - 10)
            self.root.geometry(f"+{self.root.winfo_x()}+{new_y}")

LOGGER = Overlay()
def log(msg): LOGGER.log(msg)

# ---------------------- 暂停/恢复 控制 ----------------------
def on_toggle_pause():
    """
    全局热键：暂停/继续。
    - 继续时：
        * 总是清空连续失败计数（满足“恢复后清空失败次数”的需求）
        * 若上次因“桶满”暂停，则清零“本桶计数”（不影响全局 SUCC/TOTAL）
        * 不管因何恢复，都从头重开一轮
    """
    global PAUSE_REASON, BUCKET_SUCC
    if not PAUSE_FLAG.is_set():
        # 运行中 → 进入“手动暂停”
        PAUSE_REASON = 'manual'
        PAUSE_FLAG.set()
        mouse_up()
        log(f"⏸ 暂停（按 '{CFG.keys.pause_toggle.upper()}' 继续；按 '{CFG.keys.exit_key.upper()}' 退出）")
    else:
        # 从暂停 → 恢复
        # 清空连续失败
        if FAIL_STREAK > 0:
            log("恢复 → 清空连续失败计数")
        reset_fail_streak()
        # 桶满暂停：清零“本桶计数”
        if PAUSE_REASON == 'bucket_full' and BUCKET_SUCC > 0:
            log(f"恢复 → 桶满计数 {BUCKET_SUCC} 清零（全局累计不变）")
            BUCKET_SUCC = 0
        PAUSE_REASON = None
        log("继续钓鱼：从头开始一轮")
        RESUME_RESTART.set()
        PAUSE_FLAG.clear()

def on_toggle_overlay():
    """全局热键：隐藏/显示左下角日志框（不影响终端输出）"""
    LOGGER.toggle_visible()
    # 也打印到终端，方便在隐藏状态下知晓
    print(f"[{time.strftime('%H:%M:%S')}] 切换日志框：{'显示' if LOGGER.visible else '隐藏'}")

def check_controls():
    # 任何时刻：若收到退出请求，立即抛出
    if EXIT_FLAG.is_set() or keyboard.is_pressed(CFG.keys.exit_key):
        raise KeyboardInterrupt

    # 暂停：阻塞直到恢复或退出
    if PAUSE_FLAG.is_set():
        mouse_up()
        while PAUSE_FLAG.is_set() and not EXIT_FLAG.is_set():
            # 暂停期间也允许按 q 直接退出
            if keyboard.is_pressed(CFG.keys.exit_key):
                EXIT_FLAG.set()
                break
            time.sleep(0.05)

        # 若此时是退出，则立即退出
        if EXIT_FLAG.is_set():
            raise KeyboardInterrupt

        # 恢复后统一从头开新一轮
        if RESUME_RESTART.is_set():
            RESUME_RESTART.clear()
            raise RestartRound

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

# ---------------------- （整合）比例换算 & 标注工具 ----------------------
def _scale_point(pt: Tuple[int, int], w: int, h: int,
                 base_w: int, base_h: int) -> Tuple[int, int]:
    sx, sy = w / base_w, h / base_h
    x, y = int(round(pt[0] * sx)), int(round(pt[1] * sy))
    return max(0, min(w - 1, x)), max(0, min(h - 1, y))

def _scale_points(points: Sequence[Tuple[int, int]], w: int, h: int,
                  base_w: int, base_h: int) -> List[Tuple[int, int]]:
    return [_scale_point(p, w, h, base_w, base_h) for p in points]

def _mark_and_save(img_path: Path,
                   points: Sequence[Tuple[int, int]],
                   labels: Sequence[str],
                   suffix: str = "_marked") -> Tuple[List[Tuple[int, int]], Tuple[int, int]]:
    """
    生成校验图（≅ mark_points.py 的行为）：
    - 自动按图片分辨率缩放基准点；
    - 在原图上画圆点与标签，输出 *_marked.png；
    - 返回使用的坐标与图片分辨率。
    """
    if not img_path.exists():
        log(f"[WARN] 找不到图片 {img_path}")
        return [], (0, 0)

    img = cv.imread(str(img_path))
    if img is None:
        log(f"[WARN] 读取失败 {img_path}")
        return [], (0, 0)

    h, w = img.shape[:2]
    base_w, base_h = MP_BASE_SIZE
    need_scale = (w, h) != (base_w, base_h)
    pts_use = _scale_points(points, w, h, base_w, base_h) if need_scale else list(points)

    note = "≠ 基准，已按比例换算" if need_scale else "为基准尺寸，直接使用原坐标"
    log(f"[INFO] {img_path.name}: 检测到分辨率 {w}x{h}，{note}。")

    for (x, y), text in zip(pts_use, labels):
        cv.circle(img, (x, y), MK_RADIUS, MK_COLOR, MK_THICK, cv.LINE_AA)
        cv.putText(img, text, (x + MK_RADIUS + 4, y - 4),
                   MK_FONT, MK_FSCALE, MK_COLOR, MK_FTHICK, cv.LINE_AA)

    out_path = img_path.with_stem(img_path.stem + suffix)
    cv.imwrite(str(out_path), img)
    log(f"[OK] {out_path} 已保存")
    return pts_use, (w, h)

def _write_coord_file(kind: str, coords, res: Tuple[int, int], out_dir: Path):
    """在 mark/ 目录里输出 gauge_*.py / bucket_*.py / banner_*.py"""
    if res == (0, 0):
        log(f"[WARN] 跳过 {kind}，无有效分辨率。")
        return

    w, h = res
    fname = out_dir / f"{kind}_{w}x{h}.py"
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

    fname.write_text("\n".join(lines), encoding="utf-8")
    log(f"[INFO] 坐标已输出至 {fname}")

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
        check_controls()
        ok = ok+1 if banner_visible_once() else 0
        if ok >= stable: return True
        if timeout and time.time()-t0 > timeout: return False
        time.sleep(0.05)

def wait_banner_disappear(stable=3):
    miss = 0
    while True:
        check_controls()
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
        check_controls()
        ok = ok+1 if bucket_visible_once() else 0
        if ok >= stable: log("鱼桶已出现"); return True
        if timeout and time.time()-t0 > timeout: log("等待鱼桶出现超时"); return False
        time.sleep(0.05)

def wait_bucket_disappear(timeout=None, stable=3):
    miss = 0; log("鱼桶已出现，等待其消失（无超时）…")
    while True:
        check_controls()
        miss = miss+1 if not bucket_visible_once() else 0
        if miss >= stable: log("鱼桶消失 → 咬钩!")
        # 原实现未用 timeout，这里保持一致
        return True

# ---------------------- 基础动作 ----------------------
def cast(wrect):
    check_controls()
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

    check_controls()
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
        check_controls()
        pg.moveTo(cx, cy, duration=0.01)
        pg.mouseDown(button='left'); time.sleep(press_hold); pg.mouseUp(button='left')
        for _ in range(int(interval / 0.05)):
            if tension_gauge_start_by_Z1(): log("Z1 变黄 → 拉力盘出现"); return True
            check_controls()
            time.sleep(0.05)
        if timeout and (time.time() - start > timeout):
            log("超时：多次点按仍未出现拉力盘"); return False

def collect_fish(win_rect, press_hold=0.08):
    check_controls()
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
            check_controls()
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
            check_controls()
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
        check_controls()
        # 读取 4 点颜色 & 时间
        c1 = pg.pixel(*CFG.coords.tick_coords[1])
        c2 = pg.pixel(*CFG.coords.tick_coords[2])
        c3 = pg.pixel(*CFG.coords.tick_coords[3])
        c4 = pg.pixel(*CFG.coords.tick_coords[4])
        elapsed = time.time() - tension_start_ts

        # 若拉力盘消失，由外层判断成功/空军
        if not (is_color_white(c1) or is_color_yellow(c1) or
                is_color_white(c2) or is_color_yellow(c2) or
                is_color_white(c3) or is_color_yellow(c3) or
                is_color_white(c4) or is_color_yellow(c4)):
            log("拉力盘消失（由外层判断成功 / 空军）")
            return True

        # ------------ Phase B : 固定节奏 ------------
        if phaseB:
            # 第一次进入 B：先拉到 Z3；之后循环：拉到 Z3 → 松 固定秒
            if first_B_cycle:
                first_B_cycle = False
            else:
                for _ in range(int(CFG.timings.phaseB_release_sec / 0.05)):
                    check_controls(); time.sleep(0.05)

            # 收线到 Z3
            mouse_down()
            try:
                while not is_color_yellow(pg.pixel(*CFG.coords.tick_coords[3])):
                    check_controls()
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
                    check_controls()
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
                    check_controls()
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
        check_controls()
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

    for _ in range(int(CFG.timings.post_tension_check_delay / 0.05)):
        check_controls(); time.sleep(0.05)
    if not banner_visible_once():
        log("拉力盘消失后未见提示框 → 空军")
        return False
    wait_banner_visible(timeout=CFG.timings.banner_wait_timeout, stable=CFG.timings.banner_wait_stable)
    log("检测到黄色提示框 → 开始收鱼")

    for _ in range(CFG.timings.collect_cycles_max):
        check_controls()
        if not banner_visible_once(): break
        collect_fish(win_rect, press_hold=CFG.timings.collect_press_hold)
        for _ in range(int(CFG.timings.collect_cycle_sleep / 0.05)):
            check_controls(); time.sleep(0.05)
    if banner_visible_once():
        log("⚠️ 提示框未消失，收鱼失败")
        return False

    log("收鱼成功")
    return True

# ---------------------- “开始钓鱼”主循环（原 main） ----------------------
def start_fishing():
    global SUCC, TOTAL, BUCKET_SUCC, PAUSE_REASON
    try:
        # 注册全局热键（suppress=True 避免把按键传入游戏）
        keyboard.add_hotkey(CFG.keys.pause_toggle,   on_toggle_pause,   suppress=True)
        keyboard.add_hotkey(CFG.keys.exit_key,       on_exit_hotkey,    suppress=True)
        keyboard.add_hotkey(CFG.keys.overlay_toggle, on_toggle_overlay, suppress=True)

        win_rect = get_win_rect()
        log(f"窗口：{win_rect}  3 秒后开始；按 '{CFG.keys.exit_key}' 退出；按 '{CFG.keys.pause_toggle}' 暂停/继续；按 '{CFG.keys.overlay_toggle}' 隐藏/显示日志框")

        # 倒计时期间也可暂停/退出
        for i in (3, 2, 1):
            log(str(i))
            for _ in range(10):
                check_controls(); time.sleep(0.1)

        while True:
            # 单轮（内部任何阶段都可暂停；恢复后会 RestartRound）
            try:
                res = fish_one_round(win_rect)
            except RestartRound:
                # 不计入 total，不增加连败；直接从头开始
                mouse_up()
                log("▶ 恢复后从头开始新一轮…")
                continue

            TOTAL += 1
            if res:
                SUCC += 1
                BUCKET_SUCC += 1
                reset_fail_streak()
                log(f"本次成功 | 本桶 {BUCKET_SUCC}/{CFG.timings.stop_after_n_success} | 全局 {SUCC}/{TOTAL} = {SUCC/TOTAL*100:.1f}%")
            else:
                # 本轮失败
                if inc_fail_streak():
                    # 连续失败达到阈值 → 自动暂停（不退出），恢复后清空失败次数
                    log(f"连续 {CFG.max_fail_streak} 次失败 → 自动暂停（按 '{CFG.keys.pause_toggle.upper()}' 继续）")
                    PAUSE_REASON = 'fail_streak'
                    PAUSE_FLAG.set()
                    mouse_up()
                    # 统一走控制检查：等待恢复并从头开新一轮
                    try:
                        check_controls()
                    except RestartRound:
                        continue
                log(f"本次失败 | 全局 {SUCC}/{TOTAL} = {SUCC/TOTAL*100:.1f}%")

            # ✅ 鱼桶满（本桶成功数达到阈值）→ 自动暂停（不退出）
            if BUCKET_SUCC >= CFG.timings.stop_after_n_success:
                log(f"已成功 {BUCKET_SUCC} 条，达到阈值 {CFG.timings.stop_after_n_success} → 自动暂停（按 '{CFG.keys.pause_toggle.upper()}' 继续）")
                PAUSE_REASON = 'bucket_full'
                PAUSE_FLAG.set()
                mouse_up()
                # 统一走控制检查：等待恢复并从头开新一轮
                try:
                    check_controls()
                except RestartRound:
                    continue

            # 每 N 轮重新取一次窗口
            if TOTAL % CFG.timings.recalc_every == 0:
                win_rect = get_win_rect()
    except KeyboardInterrupt:
        mouse_up(); log(f"用户按 '{CFG.keys.exit_key}' 或 Ctrl+C 退出")
    except Exception as e:
        mouse_up(); log(f"主程序发生错误: {e}"); raise
    finally:
        # 防止二次进入 start_fishing() 时热键重复注册
        try:
            keyboard.unhook_all_hotkeys()
        except:
            pass

# ---------------------- 校准：窗口分辨率 → 绝对坐标 ----------------------
def _scale_for_window(win_rect):
    """把基准点（以 1920×1080 为基准）按窗口大小缩放，并加上窗口偏移，得到‘屏幕绝对坐标’"""
    L, T, W, H = win_rect
    base_w, base_h = MP_BASE_SIZE
    sx, sy = W / base_w, H / base_h

    def spt(x, y):  # scale + offset
        return (L + int(round(x * sx)), T + int(round(y * sy)))

    tick = {i: spt(*MP_TICK_BASE[i]) for i in sorted(MP_TICK_BASE)}
    bucket_top = [spt(*p) for p in MP_BUCKET_BASE["top"]]
    bucket_bottom = [spt(*p) for p in MP_BUCKET_BASE["bottom"]]
    bucket = {"top": bucket_top, "bottom": bucket_bottom}
    banner = [spt(*p) for p in MP_BANNER_BASE]

    return tick, bucket, banner, (sx, sy)

def _coords_to_text(tick, bucket, banner):
    lines = []
    lines.append("—— 校准后的屏幕绝对坐标 ——")
    lines.append(f"tick_coords = {{1:{tick[1]}, 2:{tick[2]}, 3:{tick[3]}, 4:{tick[4]}}}")
    lines.append(f"bucket_coords = {{'top': {bucket['top']}, 'bottom': {bucket['bottom']}}}")
    lines.append(f"banner_coords = {banner}")
    return "\n".join(lines)

def _write_back_bf_config(bf_path: Path, tick, bucket, banner) -> bool:
    """
    把坐标写回 bf_config.py：
    1) 优先：正则替换 Coords 数据类中 3 个字段的 default_factory 内容；
    2) 失败兜底：在文件末尾追加覆盖段（导入时总能覆盖）。
    """
    text = bf_path.read_text(encoding="utf-8")

    # 生成新片段（保持缩进风格）
    tick_inner = (
        f"\n        1: ({tick[1][0]}, {tick[1][1]}),  # Z1"
        f"\n        2: ({tick[2][0]}, {tick[2][1]}),  # Z2"
        f"\n        3: ({tick[3][0]}, {tick[3][1]}),  # Z3"
        f"\n        4: ({tick[4][0]}, {tick[4][1]}),  # Z4\n    "
    )
    tick_inner = "".join(tick_inner)

    bucket_inner = (
        "\n        \"top\": ["
        f"\n            ({bucket['top'][0][0]}, {bucket['top'][0][1]}),"
        f"\n            ({bucket['top'][1][0]}, {bucket['top'][1][1]}),"
        "\n        ],"
        "\n        \"bottom\": ["
        f"\n            ({bucket['bottom'][0][0]}, {bucket['bottom'][0][1]}),"
        f"\n            ({bucket['bottom'][1][0]}, {bucket['bottom'][1][1]}),"
        "\n        ],\n    "
    )

    banner_inner = (
        f"\n        ({banner[0][0]}, {banner[0][1]}),"
        f"\n        ({banner[1][0]}, {banner[1][1]}),\n    "
    )

    # 三段正则替换
    patterns = [
        (r"(tick_coords:\s*Dict\[.*?\]\s*=\s*field\(\s*default_factory=\s*lambda:\s*\{)(.*?)(\}\))",
         tick_inner),
        (r"(bucket_coords:\s*Dict\[.*?\]\s*=\s*field\(\s*default_factory=\s*lambda:\s*\{)(.*?)(\}\))",
         bucket_inner),
        (r"(banner_coords:\s*List\[.*?\]\s*=\s*field\(\s*default_factory=\s*lambda:\s*\[)(.*?)(\]\))",
         banner_inner),
    ]

    new_text = text
    ok_replace = True
    for pat, inner in patterns:
        new_text2, n = re.subn(pat, r"\1" + inner + r"\3", new_text, flags=re.S)
        if n == 0:
            ok_replace = False
        new_text = new_text2

    if ok_replace:
        bf_path.write_text(new_text, encoding="utf-8")
        return True

    # 兜底：在文件末尾追加覆盖段
    patch = []
    patch.append("\n# ===== AUTO-CALIBRATED COORDS (APPEND PATCH) =====")
    patch.append("try:")
    patch.append("    # 运行时覆盖 CFG.coords 中的 3 组坐标（屏幕绝对坐标）")
    patch.append(f"    CFG.coords.tick_coords = {{1: {tick[1]}, 2: {tick[2]}, 3: {tick[3]}, 4: {tick[4]}}}")
    patch.append(f"    CFG.coords.banner_coords = {banner}")
    patch.append(f"    CFG.coords.bucket_coords = {{'top': {bucket['top']}, 'bottom': {bucket['bottom']}}}")
    patch.append("except Exception as _e:")
    patch.append("    pass")
    bf_path.write_text(text + "\n" + "\n".join(patch) + "\n", encoding="utf-8")
    return False

def _apply_runtime_override(tick, bucket, banner):
    """即时更新内存中的 CFG.coords，使不重启也可立即生效。"""
    CFG.coords.tick_coords = {1: tick[1], 2: tick[2], 3: tick[3], 4: tick[4]}
    CFG.coords.bucket_coords = {"top": list(bucket["top"]), "bottom": list(bucket["bottom"])}
    CFG.coords.banner_coords = list(banner)

def do_calibration_interactive():
    """
    交互式校准流程：
    1) 自动检测窗口分辨率与位置 → 比例换算成“屏幕绝对坐标”，输出日志；
    2) 询问是否做图校验（y）：
         - 引导把 gauge.png / bucket.png / banner.png 放入 mark/；
         - 生成 *_marked.png 与三个 *_<WxH>.py；
    3) 询问是否写回 bf_config.py；写回后同步更新运行时 CFG。
    """
    try:
        win_rect = get_win_rect()  # (L,T,W,H)
    except Exception as e:
        log(f"[ERR] 校准失败：{e}")
        return

    tick, bucket, banner, (sx, sy) = _scale_for_window(win_rect)
    L, T, W, H = win_rect
    log(f"校准：窗口矩形 L={L}, T={T}, W={W}, H={H}；基准={MP_BASE_SIZE[0]}x{MP_BASE_SIZE[1]}；缩放系数 sx={sx:.6f}, sy={sy:.6f}")
    log(_coords_to_text(tick, bucket, banner))

    # —— 是否校验并生成标注图 —— #
    ans = input("\n是否校验坐标并生成标注图？(y/N): ").strip().lower()
    if ans == "y":
        mark_dir = Path(__file__).resolve().parent / "mark"
        mark_dir.mkdir(parents=True, exist_ok=True)
        print("\n请按 mark/example 示例裁好三张图并命名为：gauge.png / bucket.png / banner.png")
        print(f"把图片放到：{mark_dir}  后，当你准备好了，输入 y 回车继续。")
        ready = input("准备好了吗？(y/N): ").strip().lower()
        if ready == "y":
            # 1) gauge
            g_img = mark_dir / "gauge.png"
            g_pts_base = [MP_TICK_BASE[k] for k in sorted(MP_TICK_BASE)]
            g_labels   = [f"Z{k}" for k in sorted(MP_TICK_BASE)]
            g_pts, g_res = _mark_and_save(g_img, g_pts_base, g_labels)
            if g_res != (0, 0):
                _write_coord_file("gauge", g_pts, g_res, mark_dir)

            # 2) bucket
            b_img = mark_dir / "bucket.png"
            b_pts_base = MP_BUCKET_BASE["top"] + MP_BUCKET_BASE["bottom"]
            b_labels   = ["Top-1", "Top-2", "Bot-1", "Bot-2"]
            b_pts, b_res = _mark_and_save(b_img, b_pts_base, b_labels)
            if b_res != (0, 0):
                _write_coord_file("bucket", b_pts, b_res, mark_dir)

            # 3) banner
            n_img = mark_dir / "banner.png"
            n_pts_base = MP_BANNER_BASE
            n_labels   = ["B-1", "B-2"]
            n_pts, n_res = _mark_and_save(n_img, n_pts_base, n_labels)
            if n_res != (0, 0):
                _write_coord_file("banner", n_pts, n_res, mark_dir)

            print("\n请将 mark/*.png 与 mark/example/*.png 对照确认点位是否合理。")

    # —— 是否写回配置 —— #
    ans2 = input("\n是否自动替换配置文件 (bf_config.py) 中的坐标？(y/N): ").strip().lower()
    if ans2 == "y":
        bf_path = Path(__file__).resolve().parent / "bf_config.py"
        ok = _write_back_bf_config(bf_path, tick, bucket, banner)
        _apply_runtime_override(tick, bucket, banner)
        if ok:
            log("[OK] 已写回 bf_config.py（覆盖原始 default_factory 内容）并实时生效。")
        else:
            log("[OK] 已在 bf_config.py 尾部追加覆盖段，且已实时生效。")

    print("\n校准流程完成。你可以：\n  - 输入 1 继续做其它校准；\n  - 输入 2 开始钓鱼；\n  - 输入 3 退出脚本。")

# ---------------------- 主菜单入口 ----------------------
def main():
    while True:
        print("\n=========== PA-Fishing ===========")
        print("1. 校准坐标")
        print("2. 开始钓鱼")
        print("3. 退出脚本")
        print("==================================")
        choice = input("请输入选项 [1/2/3]：").strip()
        if choice == "1":
            do_calibration_interactive()
        elif choice == "2":
            start_fishing()
        elif choice == "3":
            print("再见。")
            break
        else:
            print("无效输入，请重新选择。")

if __name__ == "__main__":
    main()
