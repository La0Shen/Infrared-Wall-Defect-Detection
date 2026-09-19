"""边框填充插件(**调试用**,本项目新增)。

**本模块只新增,不改任何既有文件。** `config.py` / `pipeline.py` / `defaults.yaml`
一行未动——故参数不住在 `config/defaults.yaml` 里,而是本模块自带的
`BorderFillParams` + `scripts/run_border_debug.py` 的命令行开关。
`pipeline.run_single` 依然是原样的那一个,插件靠**在自己入口里先改图、再调它**
来生效(`scripts/run_border_debug.py`)。

思路(用户原话:"**将边框视作墙体,向内 20px 都改为背景色**"):

    边框带 = 画面最外 width_px 一圈(默认 20px,从边框**向内**数)
    fill_median:边框带 ← median(T)              整圈铺成一个常数(全图中位数)
    fill_ns    :边框带 ← cv2.inpaint(NS)        从内侧墙面往里谐波延伸,逐像素
    圈内像素:一个都不动

**两个开关是两个互斥的插件**,填的是同一条带,同时开只会互相覆盖(先平铺成中位数,
再被 NS 整条盖掉),故 `check()` **直接报错**、不静默取其一。分别开,分别看效果。

与 `detect.border_ignore_px` 的分工(两者不冲突,可以同时开):

| | 改什么 | 效果 |
|---|---|---|
| `detect.border_ignore_px` | 只扣**检测掩膜** | 边框不参与判决,**一个像素都不改** |
| 本模块 | 直接改**像素值** | 边框被替换成背景温度,前后所有统计都看不到它 |

**执行位置**:本模块改的是**读进来的原始温度**,改完再交给 `run_single` 走完整的
原方案(发射率校正 → 去噪 → 窗户掩膜 → 检测 → 特征 → 分类)。因为 `run_single`
不能被改,插件唯一能干净插入的位置就是它之前——这也正是"改完图,沿用原方案处理"
的字面做法。两点后果如实记下:

- 填进去的中位数是**原始温度**的中位数(不是校正后的);发射率校正对常数是保号的
  逐像素映射,故填完的带在后续阶段仍然是平的,只是值不同。
- `preprocess.denoise`(3×3 中值)会把接缝糊掉 1px。

**实测参考**(真实帧 640×512,`width_px=20`,详见 `logs/修改日志.md`):两种模式都会
把异常区**打碎成更多小斑块**,检出**总数上升**而不是下降;`fill_median` 还必然在
内侧接缝处留下阶跃(四条边的墙温本就不一致,左边那条是邻栋楼,比全图中位数高 3.4℃)。
两者都是这种做法的固有代价,不是 bug。

纯函数、无 I/O:只改一个温度矩阵,读写都在调用方。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np

from . import detect


@dataclass
class BorderFillParams:
    """边框填充参数(本模块自带,**不写进 `config/defaults.yaml`**)。

    两个 0/1 开关是**两个互斥的插件**;`check()` 会拒掉"同时开"与非法取值。
    """

    fill_median: int = 0       # 0=关闭,1=整圈平铺成全图中位数(一个常数)
    fill_ns: int = 0           # 0=关闭,1=用原方案 NS 修复从内侧墙面往里延伸(逐像素)
    width_px: int = 20         # 边框宽度:画面最外沿**向内** N px(0=不处理)
    inpaint_radius: int = 3    # NS 修复半径(px);同 window_mask

    def enabled(self) -> bool:
        return bool(self.fill_median or self.fill_ns)


def check(p: BorderFillParams) -> BorderFillParams:
    """校验开关与像素量,返回原对象(便于链式调用)。

    "插件之间的冲突"在这里挡住:两个开关填的是同一条边框带,同时开的话执行顺序会让
    后一个整条盖掉前一个,用户以为在做对照实验、实际只看得到后者。宁可直接报错。
    """
    for name in ("fill_median", "fill_ns"):
        v = getattr(p, name)
        if isinstance(v, bool) or not isinstance(v, int) or v not in (0, 1):
            raise ValueError("border_fill 的开关 %s 必须为 0(关闭)或 1(启用),"
                             "当前为 %r" % (name, v))
    if p.fill_median and p.fill_ns:
        raise ValueError("border_fill 的 fill_median 与 fill_ns 不能同时为 1:两者填的是"
                         "同一条边框带,同时开只会互相覆盖(先平铺成全图中位数,再被 "
                         "NS 修复整条盖掉),等于白做一次对照。请只开一个")
    for name in ("width_px", "inpaint_radius"):
        v = getattr(p, name)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError("border_fill 的 %s 必须为非负整数,当前为 %r" % (name, v))
    return p


def border_mask(shape: Tuple[int, int], width_px: int) -> np.ndarray:
    """边框带掩膜(True = 边框,含四个角);width_px=0 时全 False。

    复用 `detect.interior_mask` 求出内部、再取反。注意语义与那边相反:那边是"扣掉
    检测范围、一个像素都不改",这里是"这一圈正是要改像素的地方"。
    """
    return ~detect.interior_mask(shape, int(width_px))


def apply(T: np.ndarray, p: BorderFillParams) -> np.ndarray:
    """把边框带替换成背景温度值,返回**新数组**(不改传入的 T)。

    两个开关都关时原样返回输入(逐像素不变)。
    """
    check(p)
    T = np.asarray(T, dtype=np.float32)
    if not p.enabled():
        return T

    m = border_mask(T.shape, p.width_px)
    # width_px=0 → 掩膜全 False;宽到没有内部像素 → 整幅都是边框。两种都原样返回:
    # 后者若是照填,会把整张图涂成一个值(与 border_ignore_px 覆盖全图时回退同一口径)
    if not m.any() or not (~m).any():
        return T

    if p.fill_median:
        # 整圈铺成全图中位数:一个常数,四条边同一个值
        return np.where(m, np.float32(np.median(T)), T).astype(np.float32)

    # 原方案那套 NS 修复(与窗户掩膜用的是同一个 cv2.inpaint 参数):
    # 从内侧墙面往里谐波延伸,逐像素,不是常数
    return cv2.inpaint(T, m.astype(np.uint8) * 255,
                       float(p.inpaint_radius), cv2.INPAINT_NS)
