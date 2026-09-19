"""边框填充插件测试(调试用,纯新增模块)。

口径:边框 = 画面最外 width_px 一圈(从边框**向内**数);两种背景色实现各由一个
0/1 开关控制,且**互斥**。只测纯函数,不经管线。
"""
import numpy as np
import pytest

from thermal_inspect.border_fill import (BorderFillParams, apply as border_apply,
                                         border_mask, check)
from thermal_inspect.config import Params
from thermal_inspect.demo import make_scene
from thermal_inspect.pipeline import run_single


def _scene(size=(120, 120), seed=3):
    rng = np.random.default_rng(seed)
    return rng.normal(25.0, 0.3, size).astype(np.float32)


# ---------------------------------------------------------------- 几何

def test_border_mask_is_the_outer_ring_including_corners():
    """边框带恰好是最外 width_px 一圈,四个角也算在内。"""
    m = border_mask((100, 200), 20)
    assert m.dtype == bool
    assert m[:20, :].all() and m[-20:, :].all()
    assert m[:, :20].all() and m[:, -20:].all()
    assert not m[20:-20, 20:-20].any(), "圈内不能有任何 True"
    # 角必须被算进来(四条边各取一次不带角落的话,角上会漏)
    assert m[0, 0] and m[0, -1] and m[-1, 0] and m[-1, -1]


def test_border_mask_width_zero_is_empty():
    """width_px=0 时没有边框带。"""
    assert not border_mask((50, 50), 0).any()


def test_border_mask_oversize_is_all_true():
    """宽到覆盖全图时整幅都是边框(调用方据此跳过)。"""
    assert border_mask((64, 64), 40).all()


# ---------------------------------------------------------------- 开关校验

def test_switches_must_be_0_or_1():
    for name in ("fill_median", "fill_ns"):
        for bad in (2, -1, "ture", True, False, 1.0, None):
            p = BorderFillParams()
            setattr(p, name, bad)
            with pytest.raises(ValueError) as ei:
                check(p)
            assert name in str(ei.value), (name, bad)


def test_switches_are_mutually_exclusive():
    """两个插件填的是同一条带,同时开必须报错而不是静默取其一。"""
    with pytest.raises(ValueError) as ei:
        check(BorderFillParams(fill_median=1, fill_ns=1))
    msg = str(ei.value)
    assert "fill_median" in msg and "fill_ns" in msg, msg
    # 只开一个必须放行
    check(BorderFillParams(fill_median=1, fill_ns=0))
    check(BorderFillParams(fill_median=0, fill_ns=1))


def test_pixel_keys_must_be_nonneg_int():
    for name in ("width_px", "inpaint_radius"):
        p = BorderFillParams()
        setattr(p, name, -1)
        with pytest.raises(ValueError) as ei:
            check(p)
        assert name in str(ei.value), name


def test_apply_also_rejects_conflict():
    """apply 自己也要挡住冲突,不能只靠调用方先前调过 check。"""
    with pytest.raises(ValueError):
        border_apply(_scene(), BorderFillParams(fill_median=1, fill_ns=1))


# ---------------------------------------------------------------- 两种背景色

def test_off_returns_input_unchanged():
    """两个开关都关时逐像素不变。"""
    T = _scene()
    T2 = border_apply(T, BorderFillParams(fill_median=0, fill_ns=0))
    assert np.array_equal(T2, T)


def test_apply_does_not_mutate_input():
    """返回新数组,不就地改传入的 T(调试时可能还要拿原图对照)。"""
    T = _scene()
    before = T.copy()
    border_apply(T, BorderFillParams(fill_median=1, width_px=20))
    assert np.array_equal(T, before), "传入的 T 不该被就地修改"


def test_median_mode_flattens_ring_only():
    """fill_median:整圈铺成全图中位数,圈内一个像素都不动。"""
    T = _scene()
    T2 = border_apply(T, BorderFillParams(fill_median=1, width_px=20))
    med = float(np.median(T))

    assert np.allclose(T2[:20, :], med)
    assert np.allclose(T2[-20:, :], med)
    assert np.allclose(T2[:, :20], med)
    assert np.allclose(T2[:, -20:], med)
    assert np.array_equal(T2[20:-20, 20:-20], T[20:-20, 20:-20]), "圈内必须逐像素不动"


def test_ns_mode_is_not_a_constant():
    """fill_ns:走原方案 NS 修复,故边框不是一个常数——这是与 fill_median 的分界。"""
    T = _scene()
    T2 = border_apply(T, BorderFillParams(fill_ns=1, width_px=20))

    band = T2[:20, :]
    assert not np.allclose(band, float(np.median(T))), \
        "NS 的结果不该等于平铺常数(否则就是没走 NS 分支)"
    assert float(band.std()) > 0.0, "NS 逐像素延伸,边框内不该是死的常数"
    assert np.array_equal(T2[20:-20, 20:-20], T[20:-20, 20:-20]), "圈内必须逐像素不动"


def test_width_zero_is_noop_even_when_switch_on():
    """width_px=0 时即使开关打开也逐像素不变。"""
    T = _scene()
    for p in (BorderFillParams(fill_median=1, width_px=0),
              BorderFillParams(fill_ns=1, width_px=0)):
        assert np.array_equal(border_apply(T, p), T)


def test_oversize_width_returns_input():
    """边框宽到覆盖全图时原样返回,不崩、不把整幅涂成一个值。"""
    T = _scene(size=(64, 64))
    T2 = border_apply(T, BorderFillParams(fill_median=1, width_px=40))
    assert np.array_equal(T2, T)


# ---------------------------------------------------------------- 与既有管线串联

def test_plugin_changes_the_untouched_pipeline_result():
    """插件经既有 run_single(一行未改)确实生效,且关闭时无操作。

    这是本插件的接线方式:先改图,再交给原样的 run_single。两个方向都断言,
    否则用例是空转。
    """
    scene = make_scene()
    params = Params()

    T_ref, d_ref = run_single(scene, params)

    T_off, d_off = run_single(
        border_apply(scene, BorderFillParams(fill_median=0, fill_ns=0)), params)
    assert np.array_equal(T_off, T_ref), "关闭时经管线后仍须逐像素一致"
    assert [d.bbox for d in d_off] == [d.bbox for d in d_ref]

    for p in (BorderFillParams(fill_median=1, width_px=20),
              BorderFillParams(fill_ns=1, width_px=20)):
        T_on, _ = run_single(border_apply(scene, p), params)
        assert not np.array_equal(T_on, T_ref), \
            "开启时管线结果应确实改变(否则插件根本没接上)"
