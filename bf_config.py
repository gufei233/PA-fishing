# -*- coding: utf-8 -*-
"""
所有可调参数集中在此。修改后无需改动主程序。
注：坐标为“屏幕绝对坐标”，默认适配 1920×1080 全屏（游戏窗口左上角在 (0,0)）。
若分辨率/窗口位置不同，请自行重新取点填入。
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple, List

# ---------------------- 按键配置 ----------------------
@dataclass
class Keys:
    # 退出脚本（随时可按）
    exit_key: str = 'q'
    # 展示鱼桶时按住的键（默认使用 'c'）
    show_bucket: str = 'c'
    # 等待 60s 仍未咬钩时软退使用的按键（默认为 Esc）
    abort_wait: str = 'esc'
    # 暂停/继续（随时可按，默认 'p'）
    pause_toggle: str = 'p'

# ---------------------- 坐标配置（绝对坐标，单位：像素） ----------------------
@dataclass
class Coords:
    # 张力盘（拉力盘）四点，基于 1920×1080
    tick_coords: Dict[int, Tuple[int, int]] = field(default_factory=lambda: {
        1: (808, 1016),  # Z1
        2: (872,  952),  # Z2
        3: (961,  929),  # Z3
        4: (1048, 951),  # Z4
    })
    # 鱼桶“可见”判定（上 2 黄、下 2 米白）
    bucket_coords: Dict[str, List[Tuple[int, int]]] = field(default_factory=lambda: {
        "top":    [(1479, 336), (1768, 337)],
        "bottom": [(1509,  848), (1734,  848)],
    })
    # 上鱼黄色提示框位置（2 点同时为黄）
    banner_coords: List[Tuple[int, int]] = field(default_factory=lambda: [
        (1200, 65), (1210, 153)
    ])

# ---------------------- 时间/次数参数 ----------------------
@dataclass
class Timings:
    # 主循环中：每进行 N 次重新取一次窗口坐标
    recalc_every: int = 12
    # 成功 X 条后自动停止（进入暂停）
    stop_after_n_success: int = 5

    # —— 抛竿相关 ——
    cast_press_hold: float = 0.06       # 按住左键抛竿时长（秒）
    cast_after_sleep: float = 1.5       # 抛竿后等待时间（秒）

    # —— 展示鱼桶（show_bucket）相关 ——
    bucket_hold_ms: int = 500           # 整体持续时间（毫秒）
    bucket_swipe_ratio: float = 0.30    # 从右往左的拖拽比例（相对窗口宽度）
    bucket_use_drag: bool = True        # 采用拖拽（True）或仅移动（False）
    wait_bucket_visible_timeout: float = 2.0  # 最长等待鱼桶出现时间（秒）
    wait_bucket_visible_stable: int = 2        # 连续多少次检测到视为“出现”
    wait_bucket_disappear_stable: int = 3      # 连续多少次检测不到视为“消失”

    # —— 等咬钩/软退 ——
    wait_bite_seconds: float = 60.0     # 最多等咬钩的时长（秒）

    # —— 触发拉力盘（张力盘）相关 ——
    ensure_press_hold: float = 0.06     # 单次点按按住时长（秒）
    ensure_interval: float = 1.0        # 两次点按间隔（秒）
    ensure_timeout: float = 6.0         # 最多尝试时间（秒）

    # —— 对中阶段（Z2 → 停 → Z3） ——
    prime_pause_sec: float = 0.8        # 到 Z2 后停顿时长（秒）
    z1_stuck_threshold: float = 0.7     # 若 Z1 持续黄超过此值则触发“卡死保护”（秒）
    z1_stuck_release_sec: float = 0.5   # 触发卡死保护时的“松线”时长（秒）

    # —— Phase B  —— 
    phaseB_switch_elapsed: float = 10.0 # 从拉力盘开始计时，超过此秒数且 Z2=黄 → 切入 Phase B
    phaseB_release_sec: float = 0.8     # Phase B 内每轮“松线”固定时长（秒）

    # —— 成功提示框（黄框）相关 —— 
    post_tension_check_delay: float = 1.0   # 拉力盘消失后再次确认黄框前的等待（秒）
    banner_wait_timeout: float = 2.0        # 等黄框出现的超时（秒）
    banner_wait_stable: int = 2             # 连续多少次检测到视为“出现”
    collect_cycles_max: int = 10            # 收鱼最多尝试轮数
    collect_press_hold: float = 0.08        # 收鱼每次按住左键时长（秒）
    collect_cycle_sleep: float = 0.6        # 两次收鱼之间的间隔（秒）

# ---------------------- 叠加层（日志悬浮窗） ----------------------
@dataclass
class Overlay:
    click_through: bool = True           # 鼠标穿透（不挡住点击）
    font_name: str = "Consolas"          # 字体名
    font_size: int = 11                  # 字号

# ---------------------- 颜色/容差配置 ----------------------
@dataclass
class Colors:
    # 色样本（HEX），用于快速“近似匹配”
    yellow_samples: List[str] = field(default_factory=lambda: ["#ffaa29", "#ffb63f", "#ffaa2b"])
    white_samples:  List[str] = field(default_factory=lambda: ["#dee1c5", "#dee1cd", "#dee2ca", "#f7f3de", "#f7f4e4"])
    banner_yellows: List[str] = field(default_factory=lambda: ["#ffe84f", "#ffe952"])
    bucket_top_yellows: List[str] = field(default_factory=lambda: ["#fbd560", "#fcd35f", "#fbd35e", "#f9d460"])
    bucket_bot_beiges: List[str] = field(default_factory=lambda: ["#f4e3bb", "#f3e3bb", "#f2e2ba", "#f3e2ba"])

    # 颜色近似匹配阈值（越小越严格）
    tol: Dict[str, int] = field(default_factory=lambda: {
        "yellow": 90,       # 张力盘“黄”
        "white": 70,        # 张力盘“白”
        "banner": 80,       # 黄框
        "bucket_top": 85,   # 鱼桶上缘黄
        "bucket_bot": 85,   # 鱼桶下缘米白
    })

# ---------------------- 顶层配置 ----------------------
@dataclass
class Config:
    # 游戏窗口标题（用于聚焦及定位）
    title: str = "猛兽派对"
    # 连续失败多少次后自动暂停（原逻辑为“退出”）
    max_fail_streak: int = 3

    keys: Keys = field(default_factory=Keys)
    coords: Coords = field(default_factory=Coords)
    timings: Timings = field(default_factory=Timings)
    overlay: Overlay = field(default_factory=Overlay)
    colors: Colors = field(default_factory=Colors)

# 导出单例
CFG = Config()
