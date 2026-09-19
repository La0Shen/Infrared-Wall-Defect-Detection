"""修复前标注图(**本项目新增**):在"窗户还没被删掉"的温度图上标注运算结果。

## 它补的是哪块空白

`overlay.png` 的底图是管线**处理完**的温度矩阵——窗户掩膜那一段已经把窗户(连同
过渡带)用 `cv2.inpaint` 修复填掉,发射率校正与去噪也都做过了。人工复核时看着它,
"拍到的样子"和"图上的样子"对不上:窗户那块是平的、看不出原貌。

本模块另出一张 `overlay_preinpaint.png`:**底图取"校正+去噪后、修复前"的温度矩阵**
(窗户还在),标注与 `overlay.png` 完全一致(同轮廓、同编号、同配色、同 display 过滤)。
两张图并排看——一张看处理后的净墙,一张看原始画面 + 同样的框。

## 为什么底图是"校正+去噪后、修复前"

用户在三张候选底图里选的就是这一张:
- 相机原图的像素(大疆自己的配色):最"原本",但 `.npy` 输入没有原图,且与
  `temperature.npy` 不同源,复核时对不上数;
- 原始温度矩阵(未校正未去噪):与 `temperature.npy` 差着校正/去噪两道;
- **校正+去噪后、修复前(本张)**:与 `temperature.npy` 只差"窗户有没有被填掉"这一处,
  差异可解释、可追溯。

## 样式为什么必然与 overlay.png 一致

直接调用 `pipeline.render_overlay` 渲染,**不另写一份绘制代码**——另写一份迟早会漂
(改了那边忘了这边)。延迟导入是为了避开 `pipeline → 本模块 → pipeline` 的循环导入:
本模块只在函数体内导入 `pipeline`,模块加载期不依赖它。

## 一处如实记下的差异

两张图各自按自己的 2%~98% 分位归一化配色(`render_overlay` 的既有口径,未改),所以
同一块墙在两张图上的颜色深浅会略有不同——这是**色标**不同,不是温度不同。要看两图
逐像素对照时留意这一点。

## 落盘位置

与 `overlay.png` 同级(`final/<name>/`),文件名 `overlay_preinpaint.png`。写法沿用
"输出全在 save_results 一处"的既有约定:调用方只需把修复前的矩阵交给 `save_results`
(`debug["T_preinpaint"]`),本模块不认识目录结构。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

FILENAME = "overlay_preinpaint.png"


def render(T: np.ndarray, defects, disp=None) -> np.ndarray:
    """在修复前的温度矩阵上画结果,返回 BGR 图(与 overlay.png 逐像素同口径)。

    直接复用 `pipeline.render_overlay`,样式(轮廓粗细、编号文字、颜色映射、
    display 过滤、编号与 defects.csv 下标对齐)由它一处决定。
    """
    from . import pipeline  # 延迟导入:避开 pipeline → 本模块 → pipeline 的循环导入
    return pipeline.render_overlay(T, defects, disp)


def save(out_dir, name: str, T_pre: Optional[np.ndarray], defects, params) -> Optional[Path]:
    """写 `final/<name>/overlay_preinpaint.png`;T_pre 为 None 时**不写**(返回 None)。

    T_pre 即 `run_single` 出参 `debug["T_preinpaint"]`(校正+去噪后、修复前)。
    取不到就跳过,不做兜底——用处理后的矩阵顶替的话,这张图会变成 overlay.png 的
    重复品,比没有更坏(复核时以为看的是原画面)。
    """
    if T_pre is None:
        return None
    import cv2
    out = Path(out_dir)  # save_results 传入的已是 <输出根>/<name>
    out.mkdir(parents=True, exist_ok=True)
    p = out / FILENAME
    cv2.imwrite(str(p), render(T_pre, defects, params.display))
    return p
