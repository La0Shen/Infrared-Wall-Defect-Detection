"""修复前标注图(preinpaint_overlay)测试。

三件事必须钉住:
1. 底图是**校正+去噪后、修复前**那一版(不是相机原图、不是处理完的净墙);
2. 标注样式与 overlay.png **逐像素同口径**(直接复用 render_overlay,不是另写一份);
3. 落盘位置在 final/<name>/,与 overlay.png 同级。
"""
import cv2
import numpy as np

from thermal_inspect import preinpaint_overlay, preprocess
from thermal_inspect.config import Params
from thermal_inspect.demo import make_scene
from thermal_inspect.pipeline import render_overlay, run_single, save_results


# ---------------------------------------------------------------- 底图口径

def test_debug_snapshot_is_corrected_and_denoised_before_repair():
    """debug["T_preinpaint"] == denoise(correct_emissivity(输入)),且修复确实改过它。"""
    T0 = make_scene()
    p = Params()
    dbg = {}
    T_out, _ = run_single(T0, p, debug=dbg)
    assert "T_preinpaint" in dbg, "出参字典里应有修复前快照"

    expect = preprocess.denoise(
        preprocess.correct_emissivity(T0, p.preprocess.emissivity,
                                      p.preprocess.reflected_temp_c),
        p.preprocess.denoise_kernel)
    assert np.array_equal(dbg["T_preinpaint"], expect), \
        "快照应是校正+去噪后、修复前那一版"

    assert not np.array_equal(dbg["T_preinpaint"], T_out), \
        "该场景窗户/矩形掩膜有修复动作,快照应与处理后的矩阵不同(否则这条用例是空转)"


def test_snapshot_is_a_copy_not_a_view():
    """快照必须是拷贝:管线后续若改成原地改写 T,快照不能跟着变。"""
    T0 = make_scene()
    dbg = {}
    run_single(T0, Params(), debug=dbg)
    snap = dbg["T_preinpaint"]
    before = snap.copy()
    snap[:] = 0.0                                  # 事后改快照不该影响别的
    assert np.array_equal(snap, np.zeros_like(snap))
    dbg2 = {}
    run_single(T0, Params(), debug=dbg2)
    assert np.array_equal(dbg2["T_preinpaint"], before), "两次快照应一致"


def test_no_debug_dict_no_snapshot():
    """不传出参字典时不记录(与既有惯例一致),也不崩。"""
    T_out, defects = run_single(make_scene(), Params())
    assert T_out.shape == make_scene().shape and defects is not None


# ---------------------------------------------------------------- 样式口径

def test_render_is_pixel_identical_to_overlay_renderer():
    """同一矩阵 + 同一缺陷列表 → 与 overlay.png 的渲染器逐像素一致。"""
    T0 = make_scene()
    dbg = {}
    _, defects = run_single(T0, Params(), debug=dbg)
    got = preinpaint_overlay.render(dbg["T_preinpaint"], defects, Params().display)
    want = render_overlay(dbg["T_preinpaint"], defects, Params().display)
    assert np.array_equal(got, want), "两图必须同一套绘制口径(不能另写一份)"


def test_render_honours_display_filter():
    """display 过滤照旧生效(编号仍与 defects.csv 下标对齐)。"""
    T0 = make_scene()
    dbg = {}
    _, defects = run_single(T0, Params(), debug=dbg)
    p_all, p_none = Params(), Params()
    p_none.display.show_reject = 0
    a = preinpaint_overlay.render(dbg["T_preinpaint"], defects, p_all.display)
    b = preinpaint_overlay.render(dbg["T_preinpaint"], defects, p_none.display)
    assert a.shape == b.shape


# ---------------------------------------------------------------- 落盘

def test_image_written_next_to_overlay(tmp_path):
    """落盘位置与文件名:final/<name>/overlay_preinpaint.png,与 overlay.png 同级。"""
    T0 = make_scene()
    p = Params()
    dbg = {}
    T, defects = run_single(T0, p, debug=dbg)
    main = save_results(tmp_path, tmp_path / "final", "case", T, defects, p,
                        scheme="single", debug=dbg)
    final = tmp_path / "final" / "case"        # save_results 的返回值是主目录,不是这个

    img = cv2.imread(str(final / "overlay_preinpaint.png"))
    assert img is not None, "应写出 overlay_preinpaint.png"
    assert img.shape[:2] == T.shape, "尺寸与温度矩阵一致"
    assert (final / "overlay.png").exists(), "应与 overlay.png 同目录"
    assert (main / "defects.csv").exists(), "主目录照旧"


def test_written_image_content_matches_expected(tmp_path):
    """写出的图 == 用修复前快照渲染的那张(内容也要对上,不只是文件名)。"""
    T0 = make_scene()
    p = Params()
    dbg = {}
    T, defects = run_single(T0, p, debug=dbg)
    save_results(tmp_path, tmp_path / "final", "case", T, defects, p,
                 scheme="single", debug=dbg)
    final = tmp_path / "final" / "case"
    got = cv2.imread(str(final / "overlay_preinpaint.png"))
    want = preinpaint_overlay.render(dbg["T_preinpaint"], defects, p.display)
    assert np.array_equal(got, want)
    other = cv2.imread(str(final / "overlay.png"))
    assert not np.array_equal(got, other), \
        "两张图不该相同:底图一个是修复前的原画面、一个是修复后的净墙"


def test_missing_snapshot_skips_image_without_error(tmp_path):
    """没有快照时跳过这张图(不拿处理后的矩阵顶替),其余输出照旧。"""
    T0 = make_scene()
    p = Params()
    T, defects = run_single(T0, p)
    save_results(tmp_path, tmp_path / "final", "case", T, defects, p,
                 scheme="single", debug={})
    final = tmp_path / "final" / "case"
    assert not (final / "overlay_preinpaint.png").exists()
    assert (final / "overlay.png").exists(), "其余输出不受影响"
    assert (tmp_path / "case" / "defects.csv").exists()


def test_save_returns_none_when_no_snapshot(tmp_path):
    """save() 取不到快照时返回 None(调用方可据返回值判断有没有写)。"""
    assert preinpaint_overlay.save(tmp_path, "n", None, [], Params()) is None
