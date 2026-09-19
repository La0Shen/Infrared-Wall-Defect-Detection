"""绝对矩形掩膜法测试(调试用模块,对应 总体方案.md §2.6)。

只测纯函数,不经管线。口径:转码 = `|T − median(T)| > dt_c`(全图中位数,双侧),
再按"规则(几何四边)+ 粗边(最粗处 ≥ min_edge_px)"判矩形。
"""
import json

import numpy as np

from thermal_inspect.config import RectMaskParams
from thermal_inspect.demo import make_scene
from thermal_inspect.rect_mask import detect_rectangles, quad_angle_dev


def _scene(plants, size=(240, 240), seed=11):
    """合成温度图:背景 25℃ + 低噪声,再按 plants 扣冷区。"""
    rng = np.random.default_rng(seed)
    T = rng.normal(25.0, 0.1, size).astype(np.float32)
    for sl, dv in plants:
        T[sl] -= dv
    return T


def test_finds_clean_cold_rectangle():
    """冷方块应被找到,bbox 与植入位置对得上。"""
    T = _scene([((slice(60, 140), slice(50, 130)), 1.5)])   # 80×80 冷方块
    p = RectMaskParams(dt_c=0.5, min_area_px=300)
    mask, rects = detect_rectangles(T, p)

    assert len(rects) == 1, "应恰好找到 1 个矩形,实际 %d: %s" % (
        len(rects), [r["bbox"] for r in rects])
    r = rects[0]
    assert r["bbox"] == [50, 60, 80, 80], "bbox 应与植入位置一致: %s" % (r["bbox"],)
    assert r["angle_dev_deg"] < 15.0, "四角应接近 90°"
    assert len(r["corners"]) == 4, "corners 应是四个点"
    json.dumps(r)          # 清单必须 JSON 可序列化(approxPolyDP 返回 numpy 标量)
    assert mask[60:140, 50:130].mean() > 0.8, "掩膜应盖住矩形内部"
    assert not mask[0:20, 0:20].any(), "矩形之外不该有掩膜"


def test_finds_hot_rectangle_too():
    """双侧口径:偏热的矩形同样应被找到(这是"绝对温差 |·|"的本意)。"""
    T = _scene([((slice(60, 140), slice(50, 130)), -1.5)])  # 抬高 1.5℃ 的热方块
    p = RectMaskParams(dt_c=0.5, min_area_px=300)
    _, rects = detect_rectangles(T, p)
    assert len(rects) == 1, "热矩形也应找到: %s" % ([r["bbox"] for r in rects],)
    assert rects[0]["bbox"] == [50, 60, 80, 80]


def test_rejects_elongated_strip():
    """细长条应被 min_side_ratio 挡掉。"""
    T = _scene([((slice(30, 170), slice(95, 107)), 1.5)])   # 12×140 细长条
    p = RectMaskParams(dt_c=0.5, min_area_px=300)
    _, rects = detect_rectangles(T, p)
    assert rects == [], "细长条不应被当成规则矩形: %s" % ([r["bbox"] for r in rects],)


def test_rejects_dt_too_large():
    """dt_c 超过异常幅度时什么都不该找到。"""
    T = _scene([((slice(60, 140), slice(50, 130)), 1.5)])
    p = RectMaskParams(dt_c=5.0, min_area_px=300)
    _, rects = detect_rectangles(T, p)
    assert rects == [], "dt_c 过大时不应有检出"


# 注:没有"approx_eps 取小就否掉目标"的用例 —— 实测硬边与高斯软边的合成方块
# 在 eps=0.2%~5% 下都能过(硬边方块本身就是 4 顶点轮廓)。"eps=2% 会让真实帧的
# 窗户给出 6~10 个顶点"是**那张真实图**上的观测,合成形状复现不出来,故不假装
# 能测,只记在 rect_mask 模块注释里。


def test_hairline_rectangle_rejected_by_min_edge():
    """发丝细线框也能凑出"恰 4 顶点",但不是粗边 → 应被 min_edge_px 挡掉。

    这是"粗边"判据存在的唯一理由:只有四边逼近那一套时,1px 宽的框会被当成规则矩形。
    """
    T = np.full((240, 240), 25.0, np.float32)
    T[60:140, 50:130] -= 1.5                 # 先做一个冷方块 → 再挖回中心,只剩 1px 框
    T[61:139, 51:129] += 1.5

    thin = RectMaskParams(dt_c=0.5, min_area_px=300, min_edge_px=3.0)
    assert detect_rectangles(T, thin)[1] == [], "1px 细线框不应算粗边矩形"

    off = RectMaskParams(dt_c=0.5, min_area_px=300, min_edge_px=0.0)
    assert len(detect_rectangles(T, off)[1]) == 1, "门槛为 0 时应放行(对照组)"


def test_thick_frame_passes_and_edge_px_is_band_width():
    """粗边框应通过,且 edge_px 量到的是**带宽**而不是被框住那块地的尺寸。"""
    T = np.full((240, 240), 25.0, np.float32)
    T[60:140, 50:130] -= 1.5                 # 80×80 冷方块
    T[68:132, 58:122] += 1.5                 # 挖回中心 → 剩 8px 带宽的粗框

    p = RectMaskParams(dt_c=0.5, min_area_px=300, min_edge_px=3.0)
    mask, rects = detect_rectangles(T, p)
    assert len(rects) == 1, "粗边框应被找到: %s" % ([r["bbox"] for r in rects],)
    # 角部两个方向都通,内切圆比带宽大 1~2px(实测 8px 带宽量到 10px),故给宽容差;
    # 关键是不落在短边 80px 上 —— 那样就说明量的是"框住那块地"而不是带宽
    assert 7.0 <= rects[0]["edge_px"] <= 11.0, \
        "edge_px 应是带宽 ≈8px,而不是短边 80px: %s" % (rects[0]["edge_px"],)
    assert mask[100, 90], "掩膜填的是整个四边形,框内(孔洞)也应被盖住(掩埋整个矩形)"


def test_solid_rectangle_edge_px_is_short_side():
    """实心矩形同样算粗边;此时 edge_px 落在短边上(同一把尺子)。"""
    T = _scene([((slice(60, 140), slice(50, 130)), 1.5)])   # 80×80 实心冷方块
    _, rects = detect_rectangles(T, RectMaskParams(dt_c=0.5, min_area_px=300))
    assert len(rects) == 1
    assert 76.0 <= rects[0]["edge_px"] <= 84.0, \
        "实心块的 edge_px 应接近短边 80px: %s" % (rects[0]["edge_px"],)


def test_edge_touching_border_not_inflated():
    """贴着画面边的块,粗边不应被量成整个宽度。

    cv2.distanceTransform 只看"最近的 0 像素"、不把画面外当背景,故必须先补零再算:
    否则 40px 宽、贴左边界的块会被量成 80px。
    """
    T = _scene([((slice(60, 140), slice(0, 40)), 1.5)])     # 40×80,左边界贴边
    _, rects = detect_rectangles(T, RectMaskParams(dt_c=0.5, min_area_px=300))
    assert len(rects) == 1
    assert rects[0]["bbox"][0] == 0, "应确实贴到左边界"
    assert 36.0 <= rects[0]["edge_px"] <= 44.0, \
        "贴边块的 edge_px 应是短边 40px,不是补零前的 80px: %s" % (rects[0]["edge_px"],)


def test_demo_scene_finds_true_window():
    """工作点记录:demo 场景 dt_c=3.0 时恰好找到那个真窗。

    真窗植入在 (400,330) 尺寸 90×120;检出的轮廓会沿阈值边界略微内缩一两像素,
    故比对用容差而不是精确相等。
    """
    T = make_scene()
    p = RectMaskParams(dt_c=3.0, min_area_px=300)
    _, rects = detect_rectangles(T, p)
    assert len(rects) == 1, "应恰好 1 个矩形,实际 %d: %s" % (
        len(rects), [r["bbox"] for r in rects])
    x, y, w, h = rects[0]["bbox"]
    assert abs(x - 400) <= 3 and abs(y - 330) <= 3, \
        "应命中真窗位置 (400,330): %s" % (rects[0]["bbox"],)
    assert abs(w - 90) <= 4 and abs(h - 120) <= 4, \
        "尺寸应接近 90×120: %s" % (rects[0]["bbox"],)


def test_flat_frame_yields_no_rects():
    """平坦帧:中位数为 0 温差,转码后全 0 → 无矩形且不崩。"""
    T = np.full((64, 64), 25.0, np.float32)
    mask, rects = detect_rectangles(T, RectMaskParams(dt_c=2.0))
    assert rects == []
    assert not mask.any()


def test_morph_close_zero_is_safe():
    """morph_close=0 时不做闭运算(核为 0 在 cv2 里是静默空操作,须显式守卫)。"""
    T = _scene([((slice(60, 140), slice(50, 130)), 1.5)])
    _, rects = detect_rectangles(T, RectMaskParams(dt_c=0.5, morph_close=0))
    assert len(rects) == 1


def test_quad_angle_dev_rejects_non_quad():
    """quad_angle_dev:顶点数不是 4 返回 None;正四边形接近 0。"""
    assert quad_angle_dev(np.array([[0, 0], [10, 0], [10, 10]])) is None
    square = np.array([[[0, 0]], [[10, 0]], [[10, 10]], [[0, 10]]])
    assert quad_angle_dev(square) < 1e-6
