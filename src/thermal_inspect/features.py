"""斑块特征提取:5 个特征 + 辅助量。对应 总体方案.md §4。"""
from __future__ import annotations

import math

import cv2
import numpy as np


def extract_features(blob, T: np.ndarray, ring_kernel: int = 5,
                     lap_map=None, sharp_ref=None, bbox=None) -> dict:
    """对单个斑块提取特征。

    参数:
        blob        斑块掩膜(bool 数组,全帧尺寸)
        T           温度矩阵(℃,float32,与 blob 同尺寸)
        ring_kernel 外围环带膨胀核尺寸(px)
        lap_map     预计算的 |拉普拉斯| 图(与 T 同尺寸);None 时内部计算。
                    调用方(管线)对每帧预计算一次传入,避免每斑块重复全图
                    拉普拉斯(见 pipeline)
        sharp_ref   全图 |拉普拉斯| 均值,供"边界锐/弥散"相对比较;None 时
                    由 lap_map(或内部计算)的全图均值给出
        bbox        (x, y, w, h) 斑块外接框(来自 connectedComponentsWithStats);
                    提供时斑块统计在 bbox(向外扩 ring_kernel//2 px)裁剪区进行。
                    均值/协方差/矩形面积均平移不变,结果与全图统计严格一致,
                    但避免每斑块全图扫描

    返回:
        dT          局部温差 = 斑块内均值 − 外围环带均值(℃)
        sharp       边界锐度 = 斑块边界环带内 |拉普拉斯| 均值(总体方案.md §4 定性开关;
                    环带 = 膨胀(ring_kernel)后区域 − 斑块本身)
        uniform     内部均匀度 = 斑块内温度标准差(℃)
        rect        矩形度 = 面积 / 最小外接矩形面积
        elong       伸长率 = 长轴 / 短轴(短边 <1px 时按 1px 计,退化防护)
        verticality 长轴竖直度(0~1,1=竖直),由像素坐标 PCA 主方向计算
        angle_deg   长轴与水平方向夹角(°)
        sharp_ref   全图 |拉普拉斯| 均值,供"边界锐/弥散"相对比较
    """
    blob = np.asarray(blob, dtype=bool)
    T = np.asarray(T, dtype=np.float32)
    if not blob.any():
        raise ValueError("空斑块:blob 中没有像素")

    k = int(ring_kernel)
    if bbox is not None:
        # 环带 = 膨胀(k×k)后区域 − 斑块,向外扩展 (k−1)//2 = k//2 px;
        # 裁剪域按 pad 外扩并夹到图像边界,保证裁剪区内环带与全图一致
        x, y, w, h = (int(v) for v in bbox)
        pad = max(k // 2, 1)
        py0, py1 = max(y - pad, 0), min(y + h + pad, T.shape[0])
        px0, px1 = max(x - pad, 0), min(x + w + pad, T.shape[1])
        blob_crop = blob[py0:py1, px0:px1]
        T_crop = T[py0:py1, px0:px1]
        lap_crop = np.asarray(lap_map, dtype=np.float32)[py0:py1, px0:px1] \
            if lap_map is not None else None
    else:
        blob_crop, T_crop = blob, T
        lap_crop = np.asarray(lap_map, dtype=np.float32) if lap_map is not None else None

    b8 = blob_crop.astype(np.uint8)

    # ① 局部温差 ΔT:外围环带 = 膨胀后区域 − 斑块本身
    ring = cv2.dilate(b8, np.ones((k, k), np.uint8)) > 0
    ring &= ~blob_crop
    if ring.any():
        dT = float(T_crop[blob_crop].mean() - T_crop[ring].mean())
    else:  # 斑块占满整图时,与全图中位数比较
        dT = float(T[blob].mean() - float(np.median(T)))

    # ② 边界锐度:斑块边界环带内 |拉普拉斯| 均值(全图均值为参考)
    if lap_crop is None:
        lap_crop = np.abs(cv2.Laplacian(T_crop, cv2.CV_32F))
    sharp = float(lap_crop[ring].mean()) if ring.any() else float(lap_crop[blob_crop].mean())
    if sharp_ref is None:
        lap_full = np.asarray(lap_map, dtype=np.float32) if lap_map is not None \
            else np.abs(cv2.Laplacian(T, cv2.CV_32F))
        sharp_ref = float(lap_full.mean())

    # ③ 内部均匀度:斑块内温度标准差
    uniform = float(T_crop[blob_crop].std())

    # ④⑤ 矩形度 + 伸长率:共用一次 minAreaRect(最小外接矩形)
    # 注意:minAreaRect 需传入 N×2 点数组(传二值掩膜在新版 OpenCV 会报错),
    # 且返回的 (w, h) 顺序不保证,因此伸长率取 长边/短边。
    try:
        pts = np.argwhere(blob_crop).astype(np.int32)
        _, (ma, mi), _ = cv2.minAreaRect(pts)
        ma, mi = float(ma), float(mi)
        long_side = max(ma, mi)
        short_side = max(min(ma, mi), 1.0)  # 短边 <1px 按 1px 计(1px 宽斑块退化防护)
        elong = long_side / short_side
        rect = float(blob.sum() / max(ma * mi, 1.0))
    except cv2.error:  # <4 个点等退化:退回轴对齐外接矩形
        _, _, w, h = cv2.boundingRect(b8)
        rect = float(blob.sum() / max(w * h, 1))
        elong = 1.0

    # 长轴方向:像素坐标 PCA 主方向(不依赖 minAreaRect 的角度约定;
    # 协方差平移不变,裁剪区内计算与全图结果一致)
    ys, xs = np.nonzero(blob_crop)
    if len(xs) >= 2:
        cov = np.cov(xs.astype(np.float64), ys.astype(np.float64))
        _, evecs = np.linalg.eigh(cov)
        main = evecs[:, -1]  # 最大特征值对应的主方向
        theta = math.degrees(math.atan2(float(main[1]), float(main[0])))
        verticality = abs(math.sin(math.radians(theta)))
    else:
        theta, verticality = 0.0, 0.0

    return {
        "dT": dT,
        "sharp": sharp,
        "uniform": uniform,
        "rect": rect,
        "elong": elong,
        "verticality": verticality,
        "angle_deg": theta,
        "sharp_ref": sharp_ref,
    }
