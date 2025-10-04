# Party Animals 钓鱼脚本

> 纯像素判定 + SendInput 双通道点击，兼容性高；适配 1920×1080 & 100% DPI。

## 实现方式
- **抛竿**：中心点按住 0.06s。
- **调桶**：`C` 长按 + 鼠标左滑（用 pyautogui 拖动）；鱼桶可见/消失采用 4 像素点（上两黄、下两米白）**同时满足**判定。
- **咬钩**：鱼桶消失即咬钩。
- **首次收线**：以抛竿同款点击节奏点按，直到 **Z1 像素变黄**。
- **缓慢收线至中位**：**Z2 → 停 0.8s → Z3**，带 **Z1 卡死保护**（Z1 连续黄>0.7s 则松 0.5s 再继续）。
- **正式收线（计时 10s）**：
  - **0~10s（Phase A）**：Z2↔Z3 循环（放只看 Z1/Z2；收只看 Z3/Z4；Z1/Z4 边界监控）。
  - **>10s（Phase B）**：不再检测 Z2；放线触达 Z2 即“拉到 Z3→停 0.8s”循环。
  - 全程 **Z1 防卡死**：收线时 Z1 黄→松 0.5s 继续；放线时 Z1 黄→立即改为收线直达 Z3。
- **成功判定**：**拉力盘消失后固定等待 1 秒**，若出现上方**黄色提示框**（2 像素同时黄）才算**成功**；否则**空军**。
- **收鱼**：对着屏幕中心，**按住式点击**（0.08s）循环至提示框消失（最多 10 次）。
- **鱼桶将满**：默认成功收鱼16条停止脚本，可在配置区修改`stop_after_n_success`。

## 分辨率与坐标
默认坐标基于 **1920×1080 + 100% DPI**。如果你的分辨率不同，请在代码 `CFG` 中调整这些像素点[在线图片坐标拾取](https://www.lddgo.net/image/coordinate-pick)：
- `tick_coords`（4 点）：张力盘四点 `Z1/Z2/Z3/Z4`
- `bucket_coords`（4 点）：鱼桶可见判定（上 2 黄、下 2 米白）
- `bucket_flag_coord`（1 点）：**(1680,821)**，用于“鱼桶将满”判定
- `banner_coords`（2 点）：上鱼黄色提示框（2 点均为黄）
> 调整后截图张力盘、鱼桶与提示框并使用mark内的脚本确认像素点标记是否准确。如果颜色偏差较大，可微调 `_near(..., tol=...)` 的容差（建议 ±10 范围内调整）。

## 运行环境
- Windows 
- Python 3.9+  
- `pip install opencv-python numpy pyautogui pygetwindow pywin32 keyboard pillow mss`

## 常见问题
- **点击无效**：以管理员运行；检查输入法；把 `press_hold` 提高到 0.08~0.1。
- **像素误判**：确认 DPI 100%，并校准坐标；必要时增大颜色容差或自行修改对应像素点的颜色[在线图片取色器](https://photokit.com/colors/eyedropper/?lang=zh)
- **提示框延迟**：脚本已固定等待 1 秒再判断，如仍偏慢可改成 1.2s。
## 使用
- 下载脚本压缩包并解压，在`better_fisher.py`配置区配置`stop_after_n_success`，若分辨率不为**1920×1080**则还需要校准像素坐标。
- 进入自定义房间**推荐自己创建房间并加锁**，来到钓点**推荐河中间的巨石，人物不容易移动**，调出钓竿，确保鱼饵充足。
- 在脚本文件夹地址栏输入`powershell`后回车，在弹出的终端输入`python better_fisher.py`后回车，若程序没有自动切换至游戏窗口请手动切换。
- 在钓到`stop_after_n_success`中配置的数量的鱼后脚本会自动退出，手动卖鱼后重新运行脚本即可。
## 手动校准像素坐标
- 若你的分辨率不为**1920×1080**则需要手动校准坐标，你可以根据分辨率自行换算。也可以手动拾取坐标：
- 首先按照mark文件夹中的`gauge.png``bucket.png``banner.png`在游戏中截取对应图片重命名后替换原有图片，在[在线图片坐标拾取](https://www.lddgo.net/image/coordinate-pick)中根据`gauge_marked.png``bucket_marked.png``banner_marked.png`点选对应位置坐标。
- 复制结果，替换`mark_points.py`中的`tick_coords`、`bucket_coords`与`banner_coords`。
- 同样方式在文件夹内通过`python mark_points.py`运行验证脚本，查看生成的`gauge_marked.png``bucket_marked.png``banner_marked.png`坐标点是否准确，若不准确则进行微调。
- 校准完成后在`better_fisher.py`配置区替换对应坐标。
