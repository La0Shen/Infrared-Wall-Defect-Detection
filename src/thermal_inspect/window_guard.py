"""窗形渗漏保护:极端狭长的疑似窗户块,查内部温度分布再定性质(**本项目新增**)。

**本模块是纯新增文件**:算法全在这里,既有算法文件(pipeline.py `_window_mask`
原有判断、classify.py、detect.py、features.py)一行未改——只在 `_window_mask`
判出 `is_window` 之后插了几行调用 `judge()`。

## 要解决什么(test02 实测)

窗户掩膜的**块路径**为了把成排/成列的窗户合并成块,接受 `rect ≤ 0.85` 且宽高比落在
`[0.15, 6.67]` 的冷块。一条**贯穿全画幅的连续均匀冷带**也会落进这个接受域:
实测 test02 左柱(x≈86~127)原始冷块 41×378(长宽比 **9.4:1**),闭运算把邻栋楼的
冷碎块一并合并进来,bbox 被撑到 131×512(宽高比 0.256)、rect 0.307 → 被当成窗户
整块掩掉。结果 test02 输出 `{'window': 2, 'reject': 85}`,**零渗漏**。

本模块多问一道:**这么狭长的东西,到底像窗户,还是像一条渗水带?** 判据是下面的
三条"是窗户"的口径——**任一条成立就仍按窗户**,三条都不成立才判渗漏:

    极端狭长(主导原始冷块 elong ≥ elong_min,默认 4)
      且 内部温度均衡(口径①②都不成立)
      且 边缘毛糙(口径③不成立)
        → 不是窗户(按渗漏输出;区域照旧移出净墙,避免第二遍检测在同一块地方重复报)
    否则 → 沿用原判(是窗户)

## 三条"是窗户"的口径(**任一条成立**就仍按窗户)

**每条口径都有自己的开关**(`warm_on` / `edge_on` / `regular_on`),关掉的那条不参与
判决——现场想单看某一条口径的效果,直接关另外两条即可,不必去动阈值。指标无论开关
都照算,并打进 `reason`/控制台,便于"先看数值再决定开不开"。

保守取向:任一条看出"像窗户",就不释放——宁可不放,也不要放出一堆假渗漏。

① **值域分布**:外接框内 `z > warm_z` 的像素占比 `warm_frac`。
   窗排内部有**明显更暖的子结构**(实测 test02 中部窗排 0.285:室内暖色透过玻璃,
   玻璃反光也是暖的),均匀冷带没有(实测左柱 0.009)。
② **空间分布**:块内(向内腐蚀后)`|∇T| > edge_k·σ_noise` 的像素占比 `edge_frac`。
   窗排内部有**窗框/格栅/反光边界**这类强边缘(实测中部窗排 0.0141),
   均匀冷带内部完全平滑(实测左柱 0.0000)。
③ **边缘规整度** `regularity`(用户口径,公式与推导见 `regularity()`):
   **上/下沿相对各自最小二乘直线的平均偏差(px)** × **超容差偏差的占比**——
   也就是"边缘像不像一条直线"× "不规则突出占多大比例"两个量合起来。
   窗户是人造的**直边**东西(玻璃、窗框、窗间墙柱),渗水是自然蔓延的**毛边**东西。
   实测(偏离px / 超2px占比 → 规整度):人造直边物 0.13~0.29px / 0.000~0.031 → 0.65~1.00;
   test02 左柱(**真渗漏**)1.96px / 0.312 → 0.00;test01 争议竖直条 1.04px / 0.188 → 0.00。
   门槛默认 **0.50**——两头都不贴边(人造物最低 0.65,渗漏与毛糙冷斑一律 0.00)。

   旧口径"最小外接矩形周长 / 轮廓周长"**已按用户要求换掉**,原因写在 `regularity()`
   的 docstring 里:它对**端盖**过敏(端点被噪声多啃几像素,比值能掉 0.1 以上),还把
   "边缘毛糙"与"没填满外接矩形"混在一个数里,实测与真渗漏挤在一起(0.861~1.000 对
   0.767)分不开。`rect` 同理。

## 为什么不用"块内温度标准差"判均衡(最初提法,实测被否)

test02 上左柱 `std=0.560℃`、中部窗排 `std=0.529℃`,**几乎相同**:左柱沿长度方向
有 15.3→16.4℃ 的缓变,把 std 撑到了与真窗排同一量级;test01 上更没区分度(所有冷块
0.35~0.56,窗排 0.53)。同类口径(IQR / p95−p5 / 高通 std)同样分不开。要判的不是
"温度的绝对离散度",而是**"内部有没有结构"**——这就是上面两条口径的由来。

## 为什么用"主导原始冷块",不用闭运算块

闭运算块是块路径**合并出来的产物**,它的形状不代表任何真实物体。实测 test02 左柱:
原始冷块 41×378(9.4:1),闭运算后 bbox 131×512(3.9:1)。而合成场景里"三段错位窗扇
合并成的块"(`tests/test_pipeline.py::test_window_mask_block`)每个窗扇本身只有 2:1。
按原始冷块判,两者自然分开:**合并出来的块不算狭长,连续的一根才算**——这正好对上
"块路径是为了合并成排窗户"的初衷。

## 已知代价(如实记下)

真正的**单块狭长窗**(带状窗、一条细长玻璃幕)若内部既无暖子结构、又无窗框边缘,
会被本模块判成渗漏。故 `elong_min` 是主旋钮,且本模块只作用于**已经被判成窗户**的块:
紧凑窗(elong < elong_min)一律不碰。

## 参数住在哪

`config/defaults.yaml` 的 `window_guard:` 段(与主参数同一份文件,现场调参落点一致),
但**由本模块自行读取,不经过 `Params`**——`config.py` 一行未动,故 `Params` 不认识
这一段(这是刻意的,段内已注明)。代码默认值见 `WindowGuardParams`,与 YAML 里的值
一致;YAML 缺失该段时用代码默认。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from . import config as cfg

# 内部口径用的分析核(不是现场调参旋钮,故不进参数):
_GRAD_BLUR_SIGMA = 1.5   # 求 |∇T| 前的平滑 σ(px):压掉传感器噪声,留住窗框那种真边缘
_ERODE_PX = 4            # 块内"内部"的向内腐蚀量(px):把块自己的边界梯度排除在外。
                         # 实测边界梯度能到 0.2~0.4℃/px,不排除会把均匀冷带也判成"有结构"
_MIN_COMPONENT_PX = 200  # 主导冷块小于此面积就不判(形状/统计都不再可靠,沿用原判)
_END_TRIM = 0.10         # 口径③:掐掉长轴两端各 10% 的端盖——那是角部,不是"长边"
_N_BINS = 40             # 口径③:长轴分多少段取上/下沿剖面(段太粗会把毛刺平均掉)


@dataclass
class WindowGuardParams:
    """窗形渗漏保护参数(本模块自带;YAML 见 config/defaults.yaml 的 window_guard 段)。

    默认值 = test02/test01/demo 三帧实测调出来的值,详见 logs/修改日志.md J 节。
    """

    enabled: bool = True        # False=关闭整条保护(恢复旧行为:狭长冷块仍按窗户掩掉)
    # 三条口径各自的开关(用户要求):关掉的那条不参与判决,指标照算(打印出来便于
    # 现场看数值再决定要不要开)。三条都关 = 极端狭长且内部均衡的块一律释放。
    # 写 true/false 或 YAML 常见的 0/1 都认(与 enabled 同口径)。
    warm_on: bool = True        # 口径①:内部暖子结构(z > warm_z 的占比超上限)
    edge_on: bool = True        # 口径②:内部强边缘(|∇T| > edge_k·σ 的占比超上限)
    regular_on: bool = True     # 口径③:边缘十分规整(规整度 ≥ regular_min)
    elong_min: float = 4.0      # 极端狭长门槛:主导原始冷块 minAreaRect 长边/短边。
                                # 实测:真窗排/窗区块 1.1~2.7(test01 三窗 1.14~1.71、
                                # test01 窗区块 2.72、test02 中部窗排 2.52),
                                # 误判的连续冷带 9.43 → 门槛取 4 落在两者之间
    warm_z: float = 1.5         # 口径①:内部"暖子结构"的 z 门槛(与窗户掩膜的冷掩膜
                                # 阈值同量级,z 由调用方传入)
    warm_frac_max: float = 0.10  # 口径①上限:暖像素占比 ≤ 此值才算"均衡"。
                                # 实测 左柱 0.009 / 中部窗排 0.285
                                # 要关这条口径请用 warm_on(阈值设 1.0 也能关,但别这么干)
    edge_k: float = 0.85        # 口径②:内部强边缘门槛 = edge_k × σ_noise(℃/px)。
                                # 实测 σ=0.176℃ → 0.15℃/px
    edge_frac_max: float = 0.005  # 口径②上限:强边缘占比 ≤ 此值才算"均衡"。
                                # 实测 左柱 0.0000 / 中部窗排 0.0141、test01 窗区块 0.0000
                                # (test01 那块 elong 2.72 < 门槛,压根不进这道判据)
                                # 要关这条口径请用 edge_on(阈值设 1.0 也能关,但别这么干)
    regular_min: float = 0.50   # 口径③"边缘十分规整":规整度 ≥ 此值即视为窗户,不释放。
                                # 规整度 = (1 − dev_px/edge_dev_ref_px) × (1 − prot_frac)
                                # 实测:窗间墙柱/直边人造物 0.69~1.00、真渗漏与毛糙冷斑
                                # 一律 0.00 → 门槛 0.5 落在中间,两头都不贴边
                                # 要关这条口径请用 regular_on;设 0 = 恒判"规整"
                                # (保护不再释放任何块;要关整个保护请用 enabled:false)
    edge_dev_ref_px: float = 1.0  # 口径③:"多直才算直"的参照(px)。上/下沿到各自最小二乘
                                # 直线的平均偏差 = 此值 → 直线拟合这一项归零。
                                # 1px 的道理:像素化本身有 ±0.5px 锯齿底噪,再加温度阈值
                                # 抖动,一条真直边的边界也就该在 1px 内。实测 窗间墙柱
                                # 0.13~0.29px、真渗漏 1.96px、争议条 1.04px
    edge_tol_px: float = 2.0    # 口径③:"多大算突出"(px)。偏差超过此值的剖面点算一个
                                # 不规则突出/凹陷,其**占比**(prot_frac)是第二项。
                                # 实测 prot_frac:窗间墙柱 0.000~0.031、真渗漏 0.312

    def __post_init__(self):
        # 四个开关(yaml 里写 0/1 也认,与 display 段同口径);别的值报错,不静默当真
        for name in ("enabled", "warm_on", "edge_on", "regular_on"):
            v = getattr(self, name)
            if isinstance(v, bool):
                continue
            if isinstance(v, int) and v in (0, 1):
                setattr(self, name, bool(v))
                continue
            raise ValueError("window_guard 的 %s 必须为 true/false(或 0/1),当前为 %r"
                             % (name, v))


@dataclass
class GuardVerdict:
    """一次判决的结果(供调用方决定是否按渗漏输出)。"""

    is_window: bool                       # True=沿用原判(是窗户);False=不是窗户
    triggered: bool                       # 是否进入"极端狭长"判据(False=没触发,沿用原判)
    elong: float = 0.0                    # 主导原始冷块长宽比
    warm_frac: float = 0.0                # 口径①:外接框内暖结构占比
    edge_frac: float = 0.0                # 口径②:块内强边缘占比
    regularity: float = 0.0               # 口径③:边缘规整度(1.0=边界就是四条直边)
    component: Optional[np.ndarray] = None  # 主导原始冷块掩膜(按渗漏输出时当缺陷掩膜用)
    bbox: Optional[Tuple[int, int, int, int]] = None
    reason: str = ""                      # 一句话理由(打印/追溯用)


def largest_cold_component(block_mask: np.ndarray, cold: np.ndarray):
    """块内**原始冷像素**的最大连通域(即"这个块到底是哪个真实物体")。

    闭运算块是合并出来的,形状不代表任何物体;原始冷掩膜(未经闭运算)里的连通域才是。
    返回 (掩膜, bbox, 面积);块内没有原始冷像素时返回 (None, None, 0)。
    """
    raw = np.logical_and(block_mask, cold)
    if not raw.any():
        return None, None, 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(raw.astype(np.uint8),
                                                           connectivity=8)
    i = 1 + int(np.argmax(stats[1:, 4]))          # 面积最大的那一个
    x, y, w, h, area = (int(v) for v in stats[i])
    m = np.zeros(raw.shape, dtype=bool)
    m[y:y + h, x:x + w] = labels[y:y + h, x:x + w] == i
    return m, (x, y, w, h), int(area)


def elongation(mask: np.ndarray) -> float:
    """长宽比 = 最小外接矩形长边/短边(旋转不变,与 features.elong 同口径)。"""
    pts = np.argwhere(mask).astype(np.int32)
    if len(pts) < 4:
        x, y, w, h = cv2.boundingRect(mask.astype(np.uint8))
        return float(max(w, h) / max(min(w, h), 1))
    _, (ma, mi), _ = cv2.minAreaRect(pts)
    return float(max(ma, mi) / max(min(ma, mi), 1.0))


def regularity(mask: np.ndarray, dev_ref_px: float = 1.0, tol_px: float = 2.0,
               line_on: bool = True, prot_on: bool = True) -> float:
    """口径③:边缘规整度(用户口径:**边缘拟合直线的程度 × 不规则突出占比**)。

    `dev_ref_px` / `tol_px` 由调用方给(默认值与 `WindowGuardParams` 的同名参数一致);
    本函数也被 `seepage_guard` 复用——同一套算法只有这一份实现,免得两处漂。

    `line_on` / `prot_on`:两个子口径各自的开关(用户要求拆开)。关掉的那项不参与,
    分数只剩另一项;两项都关 → **恒 1.0(判为"规整")**——现场要关整条规则请用各自
    模块的 `enabled`,别用这两个(与 `window_guard` 三条口径开关同一口径)。

    只对**极端狭长**的物体用(门槛 elong_min ≥ 4),所以边界模型很明确:**两条长边**
    (+两端的端盖)。做法:

      1. 用像素坐标的 PCA 主方向把物体摆正(长轴 u、短轴 v),掐掉两端各 `_END_TRIM`
         比例的端盖(端盖是角部,不是"边"),把剩下的 u 分 `_N_BINS` 段;
      2. 每段取该段的最大/最小 v 作为**上沿/下沿剖面**,各自对 u 做**最小二乘直线拟合**;
      3. 偏差 = 剖面上的点到各自拟合直线的距离(px,带符号)。

    两个量、一个分数:

      `dev_px`    偏差绝对值的**平均**(px)      → "边缘到底像不像一条直线"
      `prot_frac` 偏差绝对值 > `edge_tol_px` 的占比 → "不规则突出/凹陷占多大比例"

      `规整度 = (1 − clip(dev_px / edge_dev_ref_px, 0, 1)) × (1 − prot_frac)`

    **为什么用绝对 px、不按物体尺寸归一**:实测把偏差按宽度归一之后,15px 宽的窗间墙柱
    (0.26px)与 31px 宽的真渗漏(0.96px)只差 1.8 倍,判不开——因为"直不直"是**栅格与
    噪声**层面的事:一条直边在图上无论多长多宽,边界都只该在 1px 内(像素化本身就有
    ±0.5px 的锯齿底噪)。1px 这个参照与项目其它 px 参数(detrend_sigma_px /
    ring_kernel / dilate_px)同口径,同一台相机同一航线可比。

    **为什么换掉原来的"最小外接矩形周长/轮廓周长"**(用户要求换):
      ① 同一根直边带子,只要端点被噪声多啃进去几像素,周长比能掉 0.1 以上——它对
         "端盖"过敏,而端盖根本不是这条判据要看的东西;
      ② 它把"边缘毛糙"和"没填满外接矩形"混在一个数里(与 `rect` 同样的毛病);
      ③ 实测:test04 的窗间墙柱(人造直边)0.861~1.000 与 test02 真渗漏 0.767 挨得太近,
         而新口径是"0.13~0.29px vs 1.96px",差一个量级。

    实测锚点(四条真实帧,`dev_px` 均值 / 超 2px 占比):
      窗间墙柱与直边人造物 0.00~0.29px / 0.000~0.031   → 规整度 0.69~1.00
      真渗漏(test02 左柱,31×377)  1.96px / 0.312      → 规整度 0.00
      争议竖直条(test01 那条)      1.04px / 0.188      → 规整度 0.00
      各类毛糙冷斑                  1.3~5.1px / 0.2~0.6 → 规整度 0.00
    """
    pts = np.argwhere(mask)
    if len(pts) < 20:
        return 0.0
    # 摆正:PCA 主方向为长轴
    p = pts[:, ::-1].astype(np.float64)          # (x, y)
    q = p - p.mean(axis=0)
    _, evecs = np.linalg.eigh(np.cov(q.T))
    u = q @ evecs[:, -1]                         # 长轴
    v = q @ evecs[:, 0]                          # 短轴
    u0, u1 = float(u.min()), float(u.max())
    span = u1 - u0
    if span <= 0.0:
        return 0.0
    keep = (u > u0 + _END_TRIM * span) & (u < u1 - _END_TRIM * span)
    if int(keep.sum()) < 20:
        return 0.0
    idx = np.clip(((u[keep] - u0) / span * _N_BINS).astype(int), 0, _N_BINS - 1)
    devs = []
    for use_max in (True, False):
        prof = np.full(_N_BINS, np.nan)
        vv = v[keep]
        for b in range(_N_BINS):
            sel = idx == b
            if sel.any():
                prof[b] = vv[sel].max() if use_max else vv[sel].min()
        ok = ~np.isnan(prof)
        if int(ok.sum()) < 5:
            continue
        xs, ys = np.arange(_N_BINS)[ok], prof[ok]
        a, b0 = np.polyfit(xs, ys, 1)            # 最小二乘直线拟合
        devs.append(ys - (a * xs + b0))
    if not devs:
        return 0.0
    dev = np.abs(np.concatenate(devs))
    score = 1.0
    if line_on:
        score *= max(1.0 - min(float(dev.mean()) / max(float(dev_ref_px), 1e-6), 1.0), 0.0)
    if prot_on:
        score *= max(1.0 - float((dev > float(tol_px)).mean()), 0.0)
    return float(score)      # 两项都关 → 1.0(恒判"规整")


def edge_fit_detail(mask: np.ndarray, tol_px: float = 2.0) -> dict:
    """`regularity` 的两个原始量:平均偏离(px)与超容差占比(供打印/追溯)。

    判据本身只用 `regularity` 的合成分数;这两个量是给人看的——现场先看数值,
    再决定门槛往哪边调。
    """
    pts = np.argwhere(mask)
    out = {"dev_px": float("nan"), "prot_frac": float("nan")}
    if len(pts) < 20:
        return out
    p = pts[:, ::-1].astype(np.float64)
    q = p - p.mean(axis=0)
    _, evecs = np.linalg.eigh(np.cov(q.T))
    u, v = q @ evecs[:, -1], q @ evecs[:, 0]
    u0, u1 = float(u.min()), float(u.max())
    span = u1 - u0
    keep = (u > u0 + _END_TRIM * span) & (u < u1 - _END_TRIM * span)
    if span <= 0.0 or int(keep.sum()) < 20:
        return out
    idx = np.clip(((u[keep] - u0) / span * _N_BINS).astype(int), 0, _N_BINS - 1)
    devs = []
    for use_max in (True, False):
        prof = np.full(_N_BINS, np.nan)
        vv = v[keep]
        for b in range(_N_BINS):
            sel = idx == b
            if sel.any():
                prof[b] = vv[sel].max() if use_max else vv[sel].min()
        ok = ~np.isnan(prof)
        if int(ok.sum()) < 5:
            continue
        xs, ys = np.arange(_N_BINS)[ok], prof[ok]
        a, b0 = np.polyfit(xs, ys, 1)
        devs.append(ys - (a * xs + b0))
    if devs:
        dev = np.abs(np.concatenate(devs))
        out["dev_px"] = float(dev.mean())
        out["prot_frac"] = float((dev > float(tol_px)).mean())
    return out


def warm_structure_frac(z: np.ndarray, bbox, warm_z: float) -> float:
    """口径①:外接框内 z > warm_z 的像素占比(内部有没有明显更暖的子结构)。"""
    x, y, w, h = bbox
    inner = z[y:y + h, x:x + w]
    if inner.size == 0:
        return 0.0
    return float((inner > warm_z).mean())


def edge_fraction(T: np.ndarray, mask: np.ndarray, sigma: float, edge_k: float) -> float:
    """口径②:块**内部**(向内腐蚀后)|∇T| > edge_k·σ_noise 的像素占比。

    腐蚀是为了把块自己的边界排除在外——边界梯度对任何块都很大(实测 0.2~0.4℃/px),
    不排除的话均匀冷带和窗排都会被判成"有结构"。块太细、腐蚀后什么都不剩时**退回整块**
    (此时量到的必然包含边界梯度 → 判成"有结构" → 沿用原判是窗户),这是有意的:
    宁可漏放,不要把细长窗当渗漏报出去。
    """
    k = 2 * _ERODE_PX + 1
    er = cv2.erode(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    if int(er.sum()) < _MIN_COMPONENT_PX:
        er = mask
    gy, gx = np.gradient(cv2.GaussianBlur(T.astype(np.float32), (0, 0), _GRAD_BLUR_SIGMA))
    g = np.hypot(gx, gy)
    thr = float(edge_k) * float(sigma)
    return float((g[er] > thr).mean())


def judge(T: np.ndarray, z: np.ndarray, cold: np.ndarray, block_mask: np.ndarray,
          sigma: float, gp: Optional[WindowGuardParams] = None,
          bbox=None) -> GuardVerdict:
    """判一个**已被判成窗户**的冷块:它到底是窗户,还是被块路径误收的均匀冷带。

    参数:
        T          温度矩阵(℃,校正+去噪后、**窗户修复之前**——修复后的图里这块已被填掉)
        z          去趋势 + MAD 标准化后的 z 分数图(与窗户掩膜用的是同一份)
        cold       原始冷掩膜(z < -window_mask.z_threshold,未经闭运算)
        block_mask 待判的窗户块掩膜(闭运算路径产出的那个块)
        sigma      MAD 噪声 σ(℃),用于口径②的强边缘门槛
        gp         参数;None 时用 current_params()
        bbox       块的外接框(仅用于记录,不作为判据)

    返回 GuardVerdict;`is_window=False` 时 `component`/`bbox` 是该按渗漏输出的那个物体。
    """
    gp = gp if gp is not None else current_params()
    if not gp.enabled:
        return GuardVerdict(is_window=True, triggered=False, reason="保护已关闭")

    comp, cbox, area = largest_cold_component(block_mask, cold)
    if comp is None:
        return GuardVerdict(is_window=True, triggered=False,
                            reason="块内无原始冷像素(闭运算合成)")
    if area < _MIN_COMPONENT_PX:
        return GuardVerdict(is_window=True, triggered=False,
                            reason="主导冷块过小(%d px)" % area)

    el = elongation(comp)
    if el < gp.elong_min:
        return GuardVerdict(is_window=True, triggered=False, elong=el,
                            reason="长宽比 %.2f < %.2f,不属极端狭长" % (el, gp.elong_min))

    # 三条口径的指标一律算出来(打印/追溯要用,现场也是看数值决定开不开),
    # 但只有开关打开的口径才参与判决
    warm_frac = warm_structure_frac(z, cbox, gp.warm_z)
    edge_frac = edge_fraction(T, comp, sigma, gp.edge_k)
    reg = regularity(comp, gp.edge_dev_ref_px, gp.edge_tol_px)
    fit = edge_fit_detail(comp, gp.edge_tol_px)
    hits = []
    if gp.warm_on and warm_frac > gp.warm_frac_max:
        hits.append("①内部有暖子结构(%.3f>%.2f)" % (warm_frac, gp.warm_frac_max))
    if gp.edge_on and edge_frac > gp.edge_frac_max:
        hits.append("②内部有强边缘(%.4f>%.4f)" % (edge_frac, gp.edge_frac_max))
    if gp.regular_on and reg >= gp.regular_min:
        hits.append("③边缘规整(%.3f≥%.2f:偏离直线 %.2fpx、超 %.0fpx 占比 %.3f)"
                    % (reg, gp.regular_min, fit["dev_px"], gp.edge_tol_px, fit["prot_frac"]))
    is_window = bool(hits)
    if is_window:
        reason = "长宽比 %.2f,%s → 仍是窗户" % (el, "、".join(hits))
    else:
        reason = ("长宽比 %.2f,暖结构 %.3f(≤%.2f%s),强边缘 %.4f(≤%.4f%s),"
                  "规整度 %.3f(<%.2f%s;偏离直线 %.2fpx、突出占比 %.3f)"
                  % (el, warm_frac, gp.warm_frac_max, "" if gp.warm_on else ",口径关闭",
                     edge_frac, gp.edge_frac_max, "" if gp.edge_on else ",口径关闭",
                     reg, gp.regular_min, "" if gp.regular_on else ",口径关闭",
                     fit["dev_px"], fit["prot_frac"]))
    return GuardVerdict(
        is_window=is_window, triggered=True, elong=el, regularity=reg,
        warm_frac=warm_frac, edge_frac=edge_frac,
        component=comp, bbox=cbox, reason=reason)


# ---------------------------------------------------------------- 参数装载

_PARAMS_CACHE: Optional[WindowGuardParams] = None
_YAML_SECTION = "window_guard"


def default_yaml_path() -> Path:
    """仓库里的 config/defaults.yaml(包目录上溯两级)。"""
    return Path(__file__).resolve().parents[2] / "config" / "defaults.yaml"


def from_yaml(path=None) -> WindowGuardParams:
    """从 YAML 的 `window_guard:` 段读参数;文件或该段缺失时用代码默认。

    键名写错照主配置的严格口径报错(复用 config._build),避免"拼错了却静默回退默认"
    这种最难查的现场故障。显式写成 null 的键也被拒(与主配置同口径)。
    """
    p = Path(path) if path is not None else default_yaml_path()
    if not p.exists():
        return WindowGuardParams()
    import yaml as _yaml
    with open(p, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh) or {}
    section = raw.get(_YAML_SECTION)
    if section is None:
        return WindowGuardParams()
    return cfg._build(WindowGuardParams, section, _YAML_SECTION)


def current_params(path=None) -> WindowGuardParams:
    """当前生效的参数(缓存)。

    优先级:显式 `set_params()` > `path` 出参 > 环境变量 THERMAL_INSPECT_WINDOW_GUARD
    指向的 YAML > 仓库 config/defaults.yaml 的 window_guard 段 > 代码默认。
    缓存是为了让管线里每个候选块不必重复读文件;现场调参后重跑进程即可生效。
    """
    global _PARAMS_CACHE
    if _PARAMS_CACHE is not None:
        return _PARAMS_CACHE
    import os
    env = os.environ.get("THERMAL_INSPECT_WINDOW_GUARD")
    _PARAMS_CACHE = from_yaml(path or env or default_yaml_path())
    return _PARAMS_CACHE


def set_params(gp: Optional[WindowGuardParams]) -> Optional[WindowGuardParams]:
    """显式覆盖参数(None=清空缓存,恢复按文件装载);返回传入值,便于链式调用。"""
    global _PARAMS_CACHE
    _PARAMS_CACHE = gp
    return gp
