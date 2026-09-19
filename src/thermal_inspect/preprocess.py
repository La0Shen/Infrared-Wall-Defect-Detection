"""预处理:发射率校正、去噪、GSD 计算。对应 总体方案.md §1.2。"""
from __future__ import annotations

import cv2
import numpy as np

SIGMA_SB = 5.67e-8  # 斯特藩-玻尔兹曼常数 W/(m²·K⁴)


def _radiance(t: np.ndarray) -> np.ndarray:
    return SIGMA_SB * (t + 273.15) ** 4


def _inv_radiance(w: np.ndarray) -> np.ndarray:
    return (w / SIGMA_SB) ** 0.25 - 273.15


def correct_emissivity(T: np.ndarray, eps: float = 0.90, t_refl: float = 20.0) -> np.ndarray:
    """发射率校正(工程简化):W(T_surf) = (W(T_meas) − (1−ε)·W(T_refl)) / ε。

    此处用斯特藩-玻尔兹曼近似;严格做法应使用 8–14µm 波段积分与 SDK 标定曲线,
    见 延伸篇.md §10.4。
    """
    eps = float(np.clip(eps, 1e-3, 1.0))
    w = (_radiance(T) - (1.0 - eps) * _radiance(t_refl)) / eps
    return _inv_radiance(np.clip(w, 0.0, None)).astype(np.float32)


def denoise(T: np.ndarray, ksize: int = 3) -> np.ndarray:
    """中值滤波去噪。

    cv2.medianBlur 对 CV_32F 仅支持 ksize=3/5,更大的奇数核(7、9…)会抛
    cv2.error,此处钳制为 5 并告警(选钳制而非报错:现场批量跑图时单参数
    配置错误不应整批中断,与 总体方案.md §8 精神一致);偶数核 +1(保持原有行为)。
    """
    k = int(ksize)
    if k % 2 == 0:
        k += 1
    if k > 5:
        if not getattr(denoise, "_warned_gt5", False):
            print("[warn] cv2.medianBlur 对 CV_32F 仅支持 ksize=3/5,"
                  "denoise_kernel=%d 已钳制为 5" % k)
            denoise._warned_gt5 = True
        k = 5
    return cv2.medianBlur(T.astype(np.float32), k)


def gsd(distance_m, divisor: float = 540.0):
    """地面采样距离 GSD ≈ 距离/540 (m/px),Mavic 3T。距离未知时返回 None。"""
    return (float(distance_m) / divisor) if distance_m else None
