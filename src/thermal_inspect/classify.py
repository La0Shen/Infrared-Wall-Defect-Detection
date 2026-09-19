"""候选斑块分类规则(规则分类,非机器学习)。对应 总体方案.md §4。"""
from __future__ import annotations

import math

from .config import ClassifyParams


def classify(features: dict, sign: str, cp: ClassifyParams) -> str:
    """按阈值规则分类。

    参数:
        features  extract_features 的输出
        sign      'warm'(z>0,热斑)或 'cold'(z<0,冷斑)
    返回:
        'window' / 'hollow' / 'seepage' / 'reject'

    注意:边界带切过的斑块,其形状由调用方回查**完整**连通域后再传入
    (见 pipeline.run_single),此处拿到的 rect/elong 已是真实形状,
    无需再为"被切过"做特判。
    """
    f = features
    sharp_ref = f.get("sharp_ref")

    # 窗户(非缺陷):冷斑 + 矩形度高 + 明显偏冷(+ 可选:边界锐利)
    # sign 守卫与 hollow/seepage 同款:z 符号与 ΔT 符号可能不一致(环带落在
    # 更热一侧),热斑不能被判为窗户而被静默剔除出缺陷清单。
    if sign == "cold" and f["rect"] > cp.window_rect and f["dT"] < cp.window_dt_c:
        if not cp.window_require_sharp or _sharp(f, sharp_ref):
            return "window"

    if sign == "warm":
        # 空鼓:偏热 + 形状不规则(+ 可选:边界弥散)
        if f["dT"] > cp.hollow_dt_c and f["rect"] < cp.hollow_rect:
            if not cp.hollow_require_diffuse or _diffuse(f, sharp_ref):
                return "hollow"
    elif sign == "cold":
        # 形状渗漏:矩形度高 + 细长。不查 ΔT —— 规则的矩形形状比温差更能
        # 说明问题(实测 ΔT 阈值漏掉形状确定的规则渗水)。
        if (f["rect"] > cp.seepage_rect and f["elong"] > cp.seepage_rect_elong):
            if (not cp.seepage_shape_require_cold
                    or f["dT"] < cp.seepage_shape_dt_c) and _vertical_ok(f, cp):
                return "seepage"

        # 渗水:偏冷 + 细长(+ 可选:长轴偏垂直)
        if f["dT"] < cp.seepage_dt_c and f["elong"] > cp.seepage_elong:
            if _vertical_ok(f, cp):
                return "seepage"

    return "reject"


def _vertical_ok(f, cp) -> bool:
    """可选的"长轴偏垂直"条件(两条渗水规则共用,避免开关被静默绕过)。"""
    return (not cp.seepage_require_vertical
            or f["verticality"] > math.cos(math.radians(cp.seepage_angle_tol_deg)))


def _sharp(f, sharp_ref):
    """边界锐利:斑块边缘锐度高于全图平均。"""
    return sharp_ref is not None and f["sharp"] > sharp_ref


def _diffuse(f, sharp_ref):
    """边界弥散:斑块边缘锐度低于全图平均。"""
    return sharp_ref is not None and f["sharp"] < sharp_ref
