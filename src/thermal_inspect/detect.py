"""方案一核心检测:去趋势 → 噪声估计 → 标准化 → 阈值 → 连通域。对应 总体方案.md §2。"""
from __future__ import annotations

import cv2
import numpy as np


def detrend(T: np.ndarray, sigma: float) -> np.ndarray:
    """去趋势:原温度图减去高斯模糊背景。σ 取缺陷半径的 2~3 倍。"""
    bg = cv2.GaussianBlur(T.astype(np.float32), (0, 0), float(sigma))
    return T.astype(np.float32) - bg


def mad_sigma(x, scale: float = 1.4826) -> float:
    """稳健噪声估计:σ_noise = MAD(x) × scale。"""
    x = np.asarray(x, dtype=np.float32)
    return float(scale * np.median(np.abs(x - np.median(x))))


def zscore(x, sigma=None) -> np.ndarray:
    """标准化:z = x / σ_noise。sigma 为 None 时自动用 MAD 估计。

    噪声估计退化链:MAD → 标准差 → 全零(平坦图像/全零输入时不做异常判定,
    置 z 全零并告警;不再用 1e-6 兜底——那会把阈值塌缩到 2.5e-6 导致全图误报)。
    """
    x = np.asarray(x, dtype=np.float32)
    if sigma is None:
        s = mad_sigma(x)
        if s == 0:
            s = float(x.std())  # 退化:MAD 对稀疏异常不敏感,退用标准差
    else:
        s = float(sigma)
    if s == 0:
        print("[warn] 噪声估计为 0(平坦图像或全零输入),z 分数置全零,跳过检测")
        return np.zeros_like(x)
    return x / s


def threshold_z(z, z_th: float = 2.5) -> dict:
    """|z|>阈值:正 z=热斑(warm),负 z=冷斑(cold)。"""
    return {"warm": z > z_th, "cold": z < -z_th}


def interior_mask(shape, border_px: int) -> np.ndarray:
    """边界带掩膜:照片最外 border_px px 视为墙(不参与检测);0=全图。

    把照片边界当成墙:最外一圈不做判决,避免窗外未拍全、边界外无墙可比
    造成的边界伪影(实测 test01 有 12 个斑块挤在左边缘 x=0)。

    只在掩膜上扣,不改像素值——图像的边界处本来就没有"外面",垫边填任何
    常数都会在四边墙面温度不一致时造出阶跃(实测四条边中位数相差 4.12℃,
    垫边后边界带 mean|z| 从 1.35 涨到 3.79),且会改变 MAD 噪声估计。

    border_px 大于等于短边一半时无内部像素,返回全 False(调用方须兜底)。
    不做 int() 强转:类型错误交给配置校验层报错,不在这里静默容忍。
    """
    keep = np.ones(shape, dtype=bool)
    if border_px > 0:
        keep[:border_px, :] = False
        keep[-border_px:, :] = False
        keep[:, :border_px] = False
        keep[:, -border_px:] = False
    return keep


def extract_blobs(mask, min_area: int = 25) -> list:
    """连通域提取,剔除面积小于 min_area 的斑块。

    返回 [{"mask": bool数组, "area": int, "bbox": (x, y, w, h)}, ...]
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    blobs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        m = np.zeros(mask.shape, dtype=bool)
        # 仅在 bbox 切片内比较(labels == i 全图比较是 O(M)/斑块),再粘贴回全帧
        m[y:y + h, x:x + w] = labels[y:y + h, x:x + w] == i
        blobs.append({
            "mask": m,
            "area": int(area),
            "bbox": (int(x), int(y), int(w), int(h)),
        })
    return blobs
