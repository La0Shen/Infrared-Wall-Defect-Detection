"""绝对矩形掩膜法(**调试用**,本项目新增)。对应 总体方案.md §2.6。

思路:直接对图片做**转码**——把温度图按"与全图中位数的绝对温差"转成一张二维
二值矩阵,对其中**规则粗边矩形**做掩埋处理。判据是**绝对**的:阈值是℃,不是 z 分数,
不依赖任何噪声统计,也不做局部背景扣除。

    二值 = |T − median(T)| > dt_c        转码:生成二维矩阵(双侧,冷热都取)
    规则 = 轮廓四边逼近恰 4 顶点 且 凸 且 四角与 90° 偏差 ≤ angle_tol_deg
           且 面积 ≥ min_area_px 且 短边/长边 ≥ min_side_ratio
    粗边 = 矩形内前景像素到最近背景像素的最大距离 ×2 ≥ min_edge_px
           (直角处两个方向都通、内切圆更大,故角部会比带宽大 1~2px)
    掩埋 = 四边形填充成掩膜 → 膨胀 → NS 修复填平 → 沿用原方案继续去噪等处理

**"粗边"是后加的判据**:光有"四边逼近恰 4 顶点"这一条,一条 1px 粗的细线框也能
凑出 4 个顶点被当成矩形。粗边判据把"有厚度"变成可量化的一条线——量的是**最粗处**
(2 × 最大内切圆半径):粗边框量到的是带宽,实心块量到的是短边,同一把尺子。
不要求形状是环形的(实心矩形也算),只要求它别是发丝。

与 window_mask 的分工:窗户掩膜走统计口径(z 分数 + 形态学),是实际在用的那套;
本模块是**调试分支**,默认关闭(`rect_mask.enabled: 0`),用来单独看"纯几何找粗边矩形"
能抓到什么、又会碰到什么,再决定要不要把结论反哺回窗户掩膜。

本模块是**纯函数、无 I/O**,与 detect.py / features.py 同定位:只做"找矩形并生成
掩膜",修复留在 pipeline。

调试时值得留意的三点(实测记录,不是设计约束):

- 阈值 `dt_c` 是这个方法的主要旋钮,取值影响很大。实测参考:合成场景里一个
  ΔT=−1.5℃ 的冷方块在 `dt_c=0.5` 就被完整找到;demo 场景 `dt_c=3.0` 恰好找到
  那个窗户;真实帧上 `dt_c` 取 1.0~3.0 会给出几个大小不一的矩形,二值占比从 26% 降到 10%。
- 四边逼近的精度 `approx_eps` 直接影响能否凑出"恰 4 个顶点":取 2% 时同一目标会
  给出 6~10 个顶点而被否掉,取 5% 才收敛到 4 个。这是调试时最容易踩的一个点。
- 粗边门槛 `min_edge_px` 目前(默认 3.0)**在实测数据上从未生效过**:test01 上
  dt_c 从 0.3 扫到 4.0,四边候选的边宽最小也有 14px。它是防发丝细线的护栏,
  不是当前的主力判据。
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .config import RectMaskParams


def quad_angle_dev(approx: np.ndarray) -> Optional[float]:
    """四点与 90° 的**最大**偏差(°);不是 4 个顶点或边退化时返回 None。

    退化边(长度为 0)会出现在轮廓自交或极靠近的点上,此时点积无意义,
    直接判为不合格而不是返回一个虚假的小角度。
    """
    if len(approx) != 4:
        return None
    p = approx.reshape(4, 2).astype(np.float64)
    worst = 0.0
    for i in range(4):
        v1, v2 = p[(i - 1) % 4] - p[i], p[(i + 1) % 4] - p[i]
        n1, n2 = float(np.linalg.norm(v1)), float(np.linalg.norm(v2))
        if n1 < 1e-6 or n2 < 1e-6:
            return None
        cos = float(np.clip(v1.dot(v2) / (n1 * n2), -1.0, 1.0))
        worst = max(worst, abs(90.0 - math.degrees(math.acos(cos))))
    return worst


def detect_rectangles(T: np.ndarray,
                      rm: RectMaskParams) -> Tuple[np.ndarray, List[dict]]:
    """转码 → 找规则粗边矩形 → 生成掩膜(不修复,修复留在 pipeline)。

    参数:
        T   温度矩阵(℃,float32)
        rm  绝对矩形掩膜参数
    返回:
        (掩膜 bool 数组(全帧尺寸), 矩形清单)

    清单每条:`bbox / corners / area_px / angle_dev_deg / side_ratio / fill_ratio /
    edge_px`,数值全部是 Python 原生 float/int(`approxPolyDP` 返回 numpy 标量,
    直接 `json.dump` 会抛 `not JSON serializable`)。

    注意:清单条数**不等于**窗户个数——窗内若有暖色窗框(十字),一个窗会裂成
    4 个四边,计数虚高;掩膜取并集,结果仍然正确。
    """
    T = np.asarray(T, dtype=np.float32)

    # 转码:生成二维二值矩阵。基准是全图中位数,阈值是绝对温差(℃),冷热双侧都取
    med = float(np.median(T))
    binary = (np.abs(T - med) > float(rm.dt_c)).astype(np.uint8)
    if rm.morph_close > 0:
        # 显式 if 守卫:np.ones((0,0)) 在 cv2.morphologyEx 里不报错、会静默
        # 变成空操作,不能指望核为 0 时自己出错
        k = int(rm.morph_close)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE,
                                  np.ones((k, k), np.uint8))

    # 粗边度量:每个前景像素到最近背景像素的距离(最大内切圆半径场),×2 即最粗处的
    # 宽度。先补一圈 0 再算、算完裁掉——cv2.distanceTransform 只认"最近的 0 像素",
    # 不把画面外当背景,贴着画面边的块会被量成整个宽度(实测左边那栋楼 89px 宽量出 174px)
    padded = cv2.copyMakeBorder(binary, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    dist = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]

    mask = np.zeros(T.shape, dtype=bool)
    rects: List[dict] = []
    contours = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)[0]
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < rm.min_area_px:
            continue
        ap = cv2.approxPolyDP(c, float(rm.approx_eps) * cv2.arcLength(c, True), True)
        if len(ap) != 4 or not cv2.isContourConvex(ap):
            continue
        dev = quad_angle_dev(ap)
        if dev is None or dev > rm.angle_tol_deg:
            continue
        (_, (ma, mi), _) = cv2.minAreaRect(c)
        ma, mi = float(ma), float(mi)
        if ma < 1e-6:
            continue
        side_ratio = mi / ma
        if side_ratio < rm.min_side_ratio:
            continue
        poly = ap.reshape(-1, 1, 2)
        # 粗边:只在四边形**范围内的前景像素**上取最大值。取前景像素而非填充后的
        # 整个矩形,粗边框量到的才是带宽而不是被框住那块地的尺寸
        filled = np.zeros(T.shape, dtype=np.uint8)
        cv2.fillPoly(filled, [poly], 1)
        inner = (binary > 0) & (filled > 0)
        edge_px = 2.0 * float(dist[inner].max()) if inner.any() else 0.0
        if edge_px < float(rm.min_edge_px):
            continue
        x, y, w, h = cv2.boundingRect(c)
        cv2.fillPoly(mask, [poly], True)
        rects.append({
            "bbox": [int(x), int(y), int(w), int(h)],
            "corners": ap.reshape(4, 2).tolist(),
            "area_px": int(area),
            "angle_dev_deg": round(float(dev), 2),
            "side_ratio": round(side_ratio, 3),
            # 粗边宽度(px):粗边框=带宽,实心块=短边。门槛正卡在这个值上
            "edge_px": round(edge_px, 1),
            # 填充率 = 轮廓面积 / 最小外接矩形面积,与 classify 的 rect 特征同口径。
            # 只作调试参考,不参与判定
            "fill_ratio": round(area / max(ma * mi, 1e-6), 3),
        })
    return mask, rects
