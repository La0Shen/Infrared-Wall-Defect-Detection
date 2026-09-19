"""合成演示场景:含空鼓/渗水/窗户的墙面温度图(供测试与演示共用)。"""
from __future__ import annotations

import cv2
import numpy as np


def make_scene(size=(512, 512), seed=0) -> np.ndarray:
    """合成一面墙的温度图(℃,float32)。

    植入目标:
      空鼓:圆形热斑(高斯缓变,边界弥散),峰值 ΔT≈+5.0℃
      渗水:竖直细长冷斑,ΔT≈−2.5℃
      窗户:冷矩形,ΔT≈−7.0℃,内部均匀、边缘带 ≈±4px 高斯软过渡带
    背景:平缓梯度 + 低噪声(模拟墙面整体温度分布与热像仪噪声)。
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size[0], 0:size[1]].astype(np.float32)

    # 背景:平缓梯度(幅度约 1℃)+ 低噪声
    T = 24.0 + 0.002 * (xx + yy) / 2.0 + rng.normal(0.0, 0.15, size).astype(np.float32)

    # 空鼓:圆形热斑,峰值 ΔT≈+5.0℃,边界弥散(高斯缓变)
    cx, cy, r = 140.0, 160.0, 28.0
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    T += 5.0 * np.exp(-(dist ** 2) / (2 * (r / 1.6) ** 2))

    # 渗水:竖直细长冷斑,ΔT≈−2.5℃。**边界带起伏,不是理想矩形**——真实渗水是沿墙
    # 自然蔓延的,边缘毛糙;这也正是 seepage_guard 的判据(边缘毛糙才像渗水,理想直边
    # 的冷条按人造构造改判非缺陷)。demo 若摆一个完美矩形,加了那条规则后就看不到渗水了。
    half = 10.0 + 3.0 * np.sin(yy / 17.0) + 3.0 * np.sin(yy / 7.0 + 1.3)
    stripe = (np.abs(xx - 350.0) < half) & (yy > 120) & (yy < 340)
    T[stripe] -= 2.5

    # 窗户:冷矩形,ΔT≈−7.0℃,内部均匀;边缘高斯软过渡(≈±4px,模拟窗框
    # 导热与去噪糊化,供验证"删除窗户+过渡带"的自适应掩膜生长)
    win = (xx > 400) & (xx < 490) & (yy > 330) & (yy < 450)
    win_t = float(np.median(T[~win])) - 7.0
    soft = cv2.GaussianBlur(win.astype(np.float32), (0, 0), 2.0)
    T = T * (1.0 - soft) + win_t * soft

    return T
