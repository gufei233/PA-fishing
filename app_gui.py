# app_gui.py
# -*- coding: utf-8 -*-
"""
Party Animals Fishing – GUI 版
依赖: PySide6, mss, opencv-python, numpy, pyautogui, pygetwindow, keyboard
"""

import json, time, ctypes, threading, traceback, sys
from dataclasses import dataclass, asdict
from typing import Dict, Tuple, List, Optional

import numpy as np
import pyautogui as pg
import pygetwindow as gw
import keyboard
import mss, cv2 as cv

# ---------------- Qt ----------------
from PySide6.QtCore    import Qt, QThread, Signal, QTimer
from PySide6.QtGui     import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QTextEdit, QGridLayout,
    QTabWidget, QFileDialog, QMessageBox
)

# ------------- SendInput -------------
SendInput = ctypes.windll.user32.SendInput
PUL = ctypes.POINTER(ctypes.c_ulong)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]
class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]
def _mouse_event(flags):
    ii = INPUT(); ii.type = 0
    ii.mi = MOUSEINPUT(0,0,0,flags,0, ctypes.cast(ctypes.pointer(ctypes.c_ulong(0)),PUL))
    SendInput(1, ctypes.byref(ii), ctypes.sizeof(ii))
def mouse_down():  pg.mouseDown(); _mouse_event(0x0002)
def mouse_up():    pg.mouseUp();   _mouse_event(0x0004)

# ---------------- Config dataclass ----------------
@dataclass
class AppConfig:
    title: str = "猛兽派对"
    exit_key: str = "q"
    recalc_every: int = 12

    tick_coords: Dict[int, Tuple[int,int]] = None
    bucket_coords: Dict[str, List[Tuple[int,int]]] = None
    banner_coords: List[Tuple[int,int]] = None

    tol_yellow: int = 90
    tol_white:  int = 70
    tol_banner:int = 80
    tol_bucket_top: int = 85
    tol_bucket_bot: int = 85

    yellow_samples_hex: str = "#ffaa29,#ffb63f,#ffaa2b"
    white_samples_hex:  str = "#dee1c5,#dee1cd,#dee2ca,#f7f3de,#f7f4e4"
    banner_samples_hex: str = "#ffe84f,#ffe952"
    bucket_top_hex:     str = "#fbd560,#fcd35f,#fbd35e,#f9d460"
    bucket_bot_hex:     str = "#f4e3bb,#f3e3bb,#f2e2ba,#f3e2ba"

    stop_after_n_success: int = 16
    phase_b_pause: float = 0.8
    bite_timeout_sec: int = 60
    consecutive_fail_limit: int = 3
    z1_rescue_hold: float = 0.5

    def __post_init__(self):
        if self.tick_coords is None:
            self.tick_coords = {1:(808,1016),2:(872,952),3:(961,929),4:(1048,951)}
        if self.bucket_coords is None:
            self.bucket_coords = {"top":[(1479,336),(1768,337)],
                                  "bottom":[(1449,878),(1814,880)]}
        if self.banner_coords is None:
            self.banner_coords = [(1200,65),(1210,153)]

    @staticmethod
    def from_dict(d:dict): cfg = AppConfig(); [setattr(cfg,k,v) for k,v in d.items()]; return cfg
    def colors(self,s): return [_hex_to_rgb(c.strip()) for c in s.split(",") if c.strip()]

# ---------------- Pixel / Color helpers ----------------
class PixelReader:
    def __init__(self): self.sct = mss.mss()
    def pixel(self,x:int,y:int)->Tuple[int,int,int]:
        shot=self.sct.grab({"left":x,"top":y,"width":1,"height":1})
        b,g,r,_=shot.raw[:4]; return (int(r),int(g),int(b))

def _hex_to_rgb(h): h=h.strip().lstrip('#'); return (int(h[0:2],16),int(h[2:4],16),int(h[4:6],16))
def near(rgb,samples,tol): 
    r,g,b=rgb
# noqa
    for sr,sg,sb in samples:
        if abs(r-sr)+abs(g-sg)+abs(b-sb)<=tol: return True
    return False
def rgb2hsv(rgb):
    arr=np.uint8([[list(rgb)]]); return tuple(int(x) for x in cv.cvtColor(arr,cv.COLOR_RGB2HSV)[0,0])
def is_y(rgb,samples,tol):
    if near(rgb,samples,tol): return True
    h,s,v = rgb2hsv(rgb); return 10<=h<=50 and s>=120 and v>=120
def is_w(rgb,samples,tol):
    if near(rgb,samples,tol): return True
    r,g,b=rgb; return r>=190 and g>=190 and b>=170 and max(rgb)-min(rgb)<=30

# ---------------- Core logic (thread) ----------------
class FishingCore:
    def __init__(self,cfg:AppConfig,log,stat_cb):
        self.cfg=cfg; self.log=log; self.stat_cb=stat_cb; self.pr=PixelReader()
        # dynamic sample lists
        self.SY = cfg.colors(cfg.yellow_samples_hex)
        self.SW = cfg.colors(cfg.white_samples_hex)
        self.SB = cfg.colors(cfg.banner_samples_hex)
        self.ST = cfg.colors(cfg.bucket_top_hex)
        self.SBo= cfg.colors(cfg.bucket_bot_hex)

    # ---- window helpers
    def focus(self): 
        if wins:=gw.getWindowsWithTitle(self.cfg.title):
            try:wins[0].activate()
            except:pass; time.sleep(0.05)
    def rect(self): 
        wins=gw.getWindowsWithTitle(self.cfg.title)
        if not wins: raise RuntimeError("找不到游戏窗口！")
        w=wins[0];return(w.left,w.top,w.width,w.height)

    # ---- detectors
    def t_colors(self): return {i:self.pr.pixel(*xy) for i,xy in self.cfg.tick_coords.items()}
    def tension_any(self): cs=self.t_colors();return any(is_w(c,self.SW,self.cfg.tol_white)or is_y(c,self.SY,self.cfg.tol_yellow)for c in cs.values())
    def z1_y(self):return is_y(self.pr.pixel(*self.cfg.tick_coords[1]),self.SY,self.cfg.tol_yellow)
    def banner_once(self):
        c1=self.pr.pixel(*self.cfg.banner_coords[0]);c2=self.pr.pixel(*self.cfg.banner_coords[1])
        return near(c1,self.SB,self.cfg.tol_banner)and near(c2,self.SB,self.cfg.tol_banner)
    def bucket_once(self):
        t1,t2=self.cfg.bucket_coords["top"]; b1,b2=self.cfg.bucket_coords["bottom"]
        return near(self.pr.pixel(*t1),self.ST,self.cfg.tol_bucket_top) and \
               near(self.pr.pixel(*t2),self.ST,self.cfg.tol_bucket_top) and \
               near(self.pr.pixel(*b1),self.SBo,self.cfg.tol_bucket_bot) and \
               near(self.pr.pixel(*b2),self.SBo,self.cfg.tol_bucket_bot)

    # ---- wait utils
    def wait_bucket_vis(self,timeout=5,stable=2):
        ok,t0=0,time.time();self.log("等待鱼桶出现…")
        while True:
            ok=ok+1 if self.bucket_once() else 0
            if ok>=stable:self.log("鱼桶已出现");return True
            if timeout and time.time()-t0>timeout:self.log("等待鱼桶出现超时");return False
            time.sleep(0.05)
    def wait_bucket_off(self,stable=3):
        miss=0;self.log("等待鱼桶消失…")
        while True:
            miss=miss+1 if not self.bucket_once() else 0
            if miss>=stable:return True; time.sleep(0.05)

    # ---- base actions
    def cast(self,rc):
        self.focus();cx,cy=(rc[0]+rc[2]//2,rc[1]+rc[3]//2)
        pg.moveTo(cx,cy,0.05); pg.mouseDown(); time.sleep(0.06); pg.mouseUp(); time.sleep(1.4)
    def show_bucket(self,rc):
        L,T,W,H=rc;start=(L+int(.8*W),T+int(.5*H));dx=-int(.3*W)
        self.focus();pg.moveTo(*start,0.05); keyboard.press('c'); time.sleep(0.1)
        pg.dragRel(dx,0,0.3,button='left'); pg.mouseUp(); keyboard.release('c'); time.sleep(0.12)
    def clicks_trigger(self,rc):
        cx,cy=(rc[0]+rc[2]//2,rc[1]+rc[3]//2); self.log("点击触发拉力盘…")
        st=time.time()
        while time.time()-st<6:
            pg.moveTo(cx,cy,0.01); mouse_down(); time.sleep(0.06); mouse_up(); time.sleep(0.5)
            if self.z1_y():self.log("Z1 黄 → 拉力盘出现");return True
        self.log("拉力盘触发失败");return False
    def collect(self,rc):cx,cy=(rc[0]+rc[2]//2,rc[1]+rc[3]//2); pg.moveTo(cx,cy,0.01); mouse_down(); time.sleep(0.08); mouse_up(); time.sleep(0.15)

    # ---- alignment & reel (简化)
    def prime(self):
        mouse_down()
        while not is_y(self.pr.pixel(*self.cfg.tick_coords[2]),self.SY,self.cfg.tol_yellow):
            if not self.tension_any(): mouse_up(); return False
            time.sleep(0.02)
        mouse_up(); time.sleep(0.8)
        mouse_down()
        while not is_y(self.pr.pixel(*self.cfg.tick_coords[3]),self.SY,self.cfg.tol_yellow):
            if not self.tension_any(): mouse_up(); return False
            time.sleep(0.02)
        mouse_up(); self.log("对中完成"); return True

    def reel(self,ts):
        phaseB=False;first=True
        while self.tension_any():
            if not phaseB and time.time()-ts>10 and is_y(self.pr.pixel(*self.cfg.tick_coords[2]),self.SY,self.cfg.tol_yellow):
                phaseB=True;first=True; self.log("进入 Phase-B 固定节拍")
            if phaseB:
                if not first: time.sleep(self.cfg.phase_b_pause)
                first=False; mouse_down()
                while not is_y(self.pr.pixel(*self.cfg.tick_coords[3]),self.SY,self.cfg.tol_yellow):
                    if not self.tension_any(): mouse_up(); return
                    time.sleep(0.02)
                mouse_up(); continue
            else:
                # 简版 A 状态机：放到 Z2 收到Z3
                if is_y(self.pr.pixel(*self.cfg.tick_coords[2]),self.SY,self.cfg.tol_yellow):
                    mouse_down()
                    while not is_y(self.pr.pixel(*self.cfg.tick_coords[3]),self.SY,self.cfg.tol_yellow):
                        if not self.tension_any(): mouse_up();return
                        time.sleep(0.02)
                    mouse_up()
        self.log("拉力盘消失")

    # ---- one round
    def one_round(self,rc)->bool:
        self.cast(rc); self.log("抛竿完成")
        self.show_bucket(rc); self.log("调桶…")
        if not self.wait_bucket_vis(2,2):
            self.show_bucket(rc)
            if not self.wait_bucket_vis(2,2): return False
        st=time.time()
        while self.bucket_once():
            if time.time()-st >= self.cfg.bite_timeout_sec:
                self.log("超时未咬钩 → Esc")
                keyboard.press_and_release('esc'); self.wait_bucket_off();return False
            time.sleep(0.05)
        self.log("咬钩!")
        if not self.clicks_trigger(rc): return False
        if not self.prime():return False
        self.reel(time.time())
        time.sleep(1.0)
        if not self.banner_once(): return False
        self.log("收鱼…")
        for _ in range(10):
            if not self.banner_once(): break
            self.collect(rc)
            time.sleep(0.6)
        return not self.banner_once()

# --------------- Worker thread ----------------
class Worker(QThread):
    sig_log=Signal(str); sig_cnt=Signal(int,int,int); sig_done=Signal(str)
    def __init__(self,cfg):super().__init__(); self.cfg=cfg; self.stop=False
    def log(self,s): self.sig_log.emit(s)
    def run(self):
        try:
            core=FishingCore(self.cfg,self.log,lambda a,b,c:None)
            rc=core.rect();self.log(f"窗口 {rc} 三秒后开始…")
            for i in (3,2,1): time.sleep(1); self.log(str(i)); 
            tot=succ=fail=0
            while not self.stop:
                res=core.one_round(rc); tot+=1
                if res: succ+=1; fail=0; self.log(f"成功 {succ}/{tot}")
                else:   fail+=1;  self.log(f"失败 连败{fail}/{self.cfg.consecutive_fail_limit}")
                self.sig_cnt.emit(succ,tot,fail)
                if succ>=self.cfg.stop_after_n_success: self.sig_done.emit("success_limit");return
                if fail>=self.cfg.consecutive_fail_limit: self.sig_done.emit("fail_limit");return
                if tot%self.cfg.recalc_every==0: rc=core.rect()
            self.sig_done.emit("stopped")
        except Exception as e:
            self.sig_log.emit(str(e)+"\n"+traceback.format_exc()); self.sig_done.emit("error")

# --------------- Coord widget ----------------
class CoordPair(QWidget):
    def __init__(self,name,x,y,parent=None):
        super().__init__(parent)
        lay=QHBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        self.lab=QLabel(name); self.sx=QSpinBox(); self.sy=QSpinBox()
        for sp in(self.sx,self.sy): sp.setRange(0,10000)
        self.sx.setValue(x); self.sy.setValue(y)
        lay.addWidget(self.lab); lay.addWidget(QLabel("X")); lay.addWidget(self.sx)
        lay.addWidget(QLabel("Y")); lay.addWidget(self.sy)
    def value(self): return (self.sx.value(),self.sy.value())
    def setValue(self,x,y): self.sx.setValue(x); self.sy.setValue(y)

# --------------- MainWindow ----------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PA Fishing GUI"); self.resize(950,720)
        self.cfg=AppConfig(); self.worker:Optional[Worker]=None
        top=QHBoxLayout(); self.btn_start=QPushButton("开始"); self.btn_stop=QPushButton("停止")
        self.btn_load=QPushButton("加载"); self.btn_save=QPushButton("保存")
        top.addWidget(self.btn_start); top.addWidget(self.btn_stop); top.addStretch(1); top.addWidget(self.btn_load); top.addWidget(self.btn_save)
        tabs=QTabWidget()

        # 参数页
        p=QGridLayout(); w_params=QWidget(); w_params.setLayout(p)
        self.ed_title=QTextEdit(self.cfg.title); self.ed_title.setFixedHeight(28)
        self.sp_success=QSpinBox(); self.sp_success.setRange(1,999); self.sp_success.setValue(self.cfg.stop_after_n_success)
        self.sp_recalc=QSpinBox(); self.sp_recalc.setRange(1,999); self.sp_recalc.setValue(self.cfg.recalc_every)
        self.dsp_pb=QDoubleSpinBox(); self.dsp_pb.setRange(0.1,2); self.dsp_pb.setSingleStep(0.1); self.dsp_pb.setValue(self.cfg.phase_b_pause)
        self.sp_bite=QSpinBox(); self.sp_bite.setRange(5,600); self.sp_bite.setValue(self.cfg.bite_timeout_sec)
        self.sp_fail=QSpinBox(); self.sp_fail.setRange(1,20); self.sp_fail.setValue(self.cfg.consecutive_fail_limit)
        row=0
        p.addWidget(QLabel("窗口标题"),row,0); p.addWidget(self.ed_title,row,1,1,3); row+=1
        p.addWidget(QLabel("成功 N 条自动停"),row,0); p.addWidget(self.sp_success,row,1)
        p.addWidget(QLabel("窗口重定位周期"),row,2); p.addWidget(self.sp_recalc,row,3); row+=1
        p.addWidget(QLabel("Phase-B 松线 (s)"),row,0); p.addWidget(self.dsp_pb,row,1)
        p.addWidget(QLabel("调桶超时 (s)"),row,2); p.addWidget(self.sp_bite,row,3); row+=1
        p.addWidget(QLabel("连续失败上限"),row,0); p.addWidget(self.sp_fail,row,1)
        # 坐标页
        w_coords=QWidget(); pc=QGridLayout(w_coords)
        self.z1=CoordPair("Z1",*self.cfg.tick_coords[1]); self.z2=CoordPair("Z2",*self.cfg.tick_coords[2])
        self.z3=CoordPair("Z3",*self.cfg.tick_coords[3]); self.z4=CoordPair("Z4",*self.cfg.tick_coords[4])
        self.t1=CoordPair("Top1",*self.cfg.bucket_coords["top"][0]); self.t2=CoordPair("Top2",*self.cfg.bucket_coords["top"][1])
        self.b1=CoordPair("Bot1",*self.cfg.bucket_coords["bottom"][0]); self.b2=CoordPair("Bot2",*self.cfg.bucket_coords["bottom"][1])
        self.ba=CoordPair("Ban1",*self.cfg.banner_coords[0]); self.bb=CoordPair("Ban2",*self.cfg.banner_coords[1])
        for i,w in enumerate([self.z1,self.z2,self.z3,self.z4,self.t1,self.t2,self.b1,self.b2,self.ba,self.bb]):
            pc.addWidget(w,i//2,i%2)

        # 颜色页
        w_col=QWidget(); pl=QGridLayout(w_col)
        self.ed_sy=QTextEdit(self.cfg.yellow_samples_hex); self.ed_sy.setFixedHeight(26)
        self.ed_sw=QTextEdit(self.cfg.white_samples_hex);  self.ed_sw.setFixedHeight(26)
        self.ed_sb=QTextEdit(self.cfg.banner_samples_hex); self.ed_sb.setFixedHeight(26)
        self.ed_st=QTextEdit(self.cfg.bucket_top_hex);     self.ed_st.setFixedHeight(26)
        self.ed_sbo=QTextEdit(self.cfg.bucket_bot_hex);    self.ed_sbo.setFixedHeight(26)
        self.tol_y=QSpinBox(); self.tol_y.setRange(10,200); self.tol_y.setValue(self.cfg.tol_yellow)
        self.tol_w=QSpinBox(); self.tol_w.setRange(10,200); self.tol_w.setValue(self.cfg.tol_white)
        self.tol_b=QSpinBox(); self.tol_b.setRange(10,200); self.tol_b.setValue(self.cfg.tol_banner)
        self.tol_t=QSpinBox(); self.tol_t.setRange(10,200); self.tol_t.setValue(self.cfg.tol_bucket_top)
        self.tol_bo=QSpinBox();self.tol_bo.setRange(10,200);self.tol_bo.setValue(self.cfg.tol_bucket_bot)
        r=0
        pl.addWidget(QLabel("指针黄样本"),r,0); pl.addWidget(self.ed_sy,r,1,1,3); r+=1
        pl.addWidget(QLabel("底盘白样本"),r,0); pl.addWidget(self.ed_sw,r,1,1,3); r+=1
        pl.addWidget(QLabel("提示黄样本"),r,0); pl.addWidget(self.ed_sb,r,1,1,3); r+=1
        pl.addWidget(QLabel("桶上黄样本"),r,0); pl.addWidget(self.ed_st,r,1,1,3); r+=1
        pl.addWidget(QLabel("桶下米白样本"),r,0);pl.addWidget(self.ed_sbo,r,1,1,3); r+=1
        pl.addWidget(QLabel("黄容差"),r,0); pl.addWidget(self.tol_y,r,1)
        pl.addWidget(QLabel("白容差"),r,2); pl.addWidget(self.tol_w,r,3); r+=1
        pl.addWidget(QLabel("提示容差"),r,0); pl.addWidget(self.tol_b,r,1)
        pl.addWidget(QLabel("桶上容差"),r,2); pl.addWidget(self.tol_t,r,3); r+=1
        pl.addWidget(QLabel("桶下容差"),r,0); pl.addWidget(self.tol_bo,r,1)

        tabs.addTab(w_params,"参数"); tabs.addTab(w_coords,"坐标"); tabs.addTab(w_col,"颜色")
        self.txt_log=QTextEdit(); self.txt_log.setReadOnly(True)
        status=QHBoxLayout(); self.lab_state=QLabel("状态：待机"); self.lab_cnt=QLabel("成功0 / 0")
        status.addWidget(self.lab_state); status.addStretch(1); status.addWidget(self.lab_cnt)
        root=QWidget(); self.setCentralWidget(root)
        lay=QVBoxLayout(root); lay.addLayout(top); lay.addWidget(tabs); lay.addLayout(status); lay.addWidget(self.txt_log)

        # connections
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_save.clicked.connect(self.save_cfg)
        self.btn_load.clicked.connect(self.load_cfg)

    # ---- config helpers
    def to_cfg(self)->AppConfig:
        c=AppConfig()
        c.title=self.ed_title.toPlainText().strip() or "猛兽派对"
        c.stop_after_n_success=self.sp_success.value()
        c.recalc_every=self.sp_recalc.value()
        c.phase_b_pause=float(self.dsp_pb.value())
        c.bite_timeout_sec=self.sp_bite.value()
        c.consecutive_fail_limit=self.sp_fail.value()
        c.tol_yellow=self.tol_y.value(); c.tol_white=self.tol_w.value()
        c.tol_banner=self.tol_b.value(); c.tol_bucket_top=self.tol_t.value(); c.tol_bucket_bot=self.tol_bo.value()
        c.yellow_samples_hex=self.ed_sy.toPlainText().strip()
        c.white_samples_hex =self.ed_sw.toPlainText().strip()
        c.banner_samples_hex=self.ed_sb.toPlainText().strip()
        c.bucket_top_hex    =self.ed_st.toPlainText().strip()
        c.bucket_bot_hex    =self.ed_sbo.toPlainText().strip()
        c.tick_coords={1:self.z1.value(),2:self.z2.value(),3:self.z3.value(),4:self.z4.value()}
        c.bucket_coords={"top":[self.t1.value(),self.t2.value()],"bottom":[self.b1.value(),self.b2.value()]}
        c.banner_coords=[self.ba.value(),self.bb.value()]
        return c
    def apply_cfg(self,c:AppConfig):
        self.ed_title.setText(c.title)
        self.sp_success.setValue(c.stop_after_n_success); self.sp_recalc.setValue(c.recalc_every)
        self.dsp_pb.setValue(c.phase_b_pause); self.sp_bite.setValue(c.bite_timeout_sec)
        self.sp_fail.setValue(c.consecutive_fail_limit)
        self.tol_y.setValue(c.tol_yellow); self.tol_w.setValue(c.tol_white); self.tol_b.setValue(c.tol_banner)
        self.tol_t.setValue(c.tol_bucket_top); self.tol_bo.setValue(c.tol_bucket_bot)
        self.ed_sy.setText(c.yellow_samples_hex); self.ed_sw.setText(c.white_samples_hex)
        self.ed_sb.setText(c.banner_samples_hex); self.ed_st.setText(c.bucket_top_hex); self.ed_sbo.setText(c.bucket_bot_hex)
        self.z1.setValue(*c.tick_coords[1]); self.z2.setValue(*c.tick_coords[2])
        self.z3.setValue(*c.tick_coords[3]); self.z4.setValue(*c.tick_coords[4])
        self.t1.setValue(*c.bucket_coords["top"][0]); self.t2.setValue(*c.bucket_coords["top"][1])
        self.b1.setValue(*c.bucket_coords["bottom"][0]); self.b2.setValue(*c.bucket_coords["bottom"][1])
        self.ba.setValue(*c.banner_coords[0]); self.bb.setValue(*c.banner_coords[1])

    # ---- logging
    def log(self,s):
        self.txt_log.append(s); self.txt_log.moveCursor(QTextCursor.End)

    # ---- btn handlers
    def start(self):
        if self.worker and self.worker.isRunning():
            self.log("已在运行中"); return
        cfg=self.to_cfg(); self.worker=Worker(cfg)
        self.worker.sig_log.connect(self.log)
        self.worker.sig_cnt.connect(lambda a,b,c:self.lab_cnt.setText(f"成功 {a}/{b} 连败{c}"))
        self.worker.sig_done.connect(lambda r:self.lab_state.setText(f"状态：结束({r})"))
        self.lab_state.setText("状态：运行中")
        self.worker.start()
    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop=True; self.log("请求停止…")
    def save_cfg(self):
        path,_=QFileDialog.getSaveFileName(self,"保存配置","config.json","JSON (*.json)")
        if path: json.dump(asdict(self.to_cfg()),open(path,"w",encoding="utf-8"),ensure_ascii=False,indent=2); QMessageBox.information(self,"OK","已保存")
    def load_cfg(self):
        path,_=QFileDialog.getOpenFileName(self,"加载配置","config.json","JSON (*.json)")
        if path:
            self.apply_cfg(AppConfig.from_dict(json.load(open(path,"r",encoding="utf-8"))))
            QMessageBox.information(self,"OK","已加载")

# --------------- entry ----------------
if __name__=="__main__":
    app=QApplication(sys.argv); app.setStyle("Fusion"); w=MainWindow(); w.show(); sys.exit(app.exec())
