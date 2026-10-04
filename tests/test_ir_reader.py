"""通用红外读取(ir_reader)测试:三种模式 + 精度闭环 + 参数校验 + 与管线串联。

**最要紧的是闭环验证**:拿一个已知的温度矩阵 → 渲染成伪彩图 → 用本模块反演回来
→ 量误差。这是唯一能回答"伪彩图到底能还原出多少温度"的办法,实测数字见
`logs/修改日志.md`(PNG 无损 ≈ 一个色阶;JPEG 因色度压缩更差)。
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from thermal_inspect import ir_reader
from thermal_inspect.config import Params
from thermal_inspect.demo import make_scene
from thermal_inspect.ir_reader import IrCalibParams, read_ir
from thermal_inspect.pipeline import run_single


@pytest.fixture(autouse=True)
def _reset_params_cache():
    """前后清缓存:覆盖过的参数是进程级的,会污染其它测试文件。"""
    ir_reader.set_params(None)
    yield
    ir_reader.set_params(None)


# ---------------------------------------------------------------- gray 模式

def test_gray_linear_mapping():
    """灰度线性映射:0 → t_min,255 → t_max,中间线性。"""
    raw = np.array([[0, 128, 255]], dtype=np.uint8)
    p = IrCalibParams(mode="gray", t_min=-10.0, t_max=30.0)
    T = ir_reader._gray_to_temp(raw, p)
    assert T[0, 0] == pytest.approx(-10.0)
    assert T[0, 1] == pytest.approx(10.0, abs=0.1)   # 128/255 本身就有量化
    assert T[0, 2] == pytest.approx(30.0)


def test_gray_16bit_uses_full_range():
    """16bit 图按 65535 归一,不是按 255(否则温度会整体偏低)。"""
    raw = np.array([[0, 32767, 65535]], dtype=np.uint16)
    p = IrCalibParams(mode="gray", t_min=0.0, t_max=100.0)
    T = ir_reader._gray_to_temp(raw, p)
    assert T[0, 2] == pytest.approx(100.0)
    assert T[0, 1] == pytest.approx(50.0, abs=0.01)


def test_gray_invert_swaps_direction():
    """invert_gray:0 表示最热的情况。"""
    raw = np.array([[0, 255]], dtype=np.uint8)
    p = IrCalibParams(mode="gray", t_min=0.0, t_max=50.0, invert_gray=True)
    T = ir_reader._gray_to_temp(raw, p)
    assert T[0, 0] == pytest.approx(50.0) and T[0, 1] == pytest.approx(0.0)


# ---------------------------------------------------------------- palette 模式

def _render(T, colormap_name="inferno", ext=".png", path=None):
    """把温度矩阵按自身范围渲染成伪彩图(模拟设备导出的热图)。"""
    lo, hi = float(T.min()), float(T.max())
    norm = np.clip((T - lo) / max(hi - lo, 1e-6), 0, 1)
    cid = ir_reader._CMAP_IDS[colormap_name]
    img = cv2.applyColorMap((norm * 255).astype(np.uint8), cid)
    out = str(path / ("hot" + ext))
    cv2.imwrite(out, img)
    return out, lo, hi


def test_palette_roundtrip_png_within_one_step(tmp_path):
    """闭环(PNG 无损):反演误差应不超过**一个色阶**的宽度。

    一个色阶 = (t_max − t_min) / 255 —— 这是伪彩图的信息论上限:8bit 只有 256 级,
    再怎么反演也不可能比这更准。
    """
    T = make_scene()
    path, lo, hi = _render(T, "inferno", ".png", tmp_path)
    T2 = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                     t_min=lo, t_max=hi))
    step = (hi - lo) / 255.0
    err = np.abs(T2 - T)
    assert err.max() <= step * 1.5, "最大误差 %.4f℃ 超过 1.5 个色阶(%.4f℃)" % (err.max(), step)
    assert err.mean() < step * 0.5, "平均误差 %.4f℃ 偏大(一个色阶 %.4f℃)" % (err.mean(), step)


def test_palette_roundtrip_jpeg_is_worse_but_bounded(tmp_path):
    """闭环(JPEG):色度压缩会让误差变大—— **如实钉住这个代价**。

    JPEG 的 4:2:0 色度子采样会改变颜色,而颜色正是伪彩图唯一的温度载体。
    这里不断言"很小",而是断言**误差量级**与量化宽度可比,防止哪天悄悄恶化。
    """
    T = make_scene()
    path, lo, hi = _render(T, "inferno", ".jpg", tmp_path)
    T2 = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                     t_min=lo, t_max=hi))
    step = (hi - lo) / 255.0
    err = np.abs(T2 - T)
    # 实测(demo 场景,量程 12.1℃):最大 28 色阶、平均 1.9 色阶。JPEG 的色度子采样
    # 在颜色突变处产生色晕,个别像素能偏出去几十个色阶——这是伪彩路线的**固有代价**,
    # 不是实现缺陷。断言按实测量级留一倍余量,防止哪天悄悄恶化。
    assert err.mean() < step * 6, "JPEG 平均误差 %.4f℃(%.1f 色阶)超出预期" % (err.mean(), err.mean()/step)
    assert err.max() < step * 60, "JPEG 最大误差 %.4f℃(%.1f 色阶)超出预期" % (err.max(), err.max()/step)
    # 关键提醒写进用例:JPEG 的最大误差(实测 1.32℃)已经接近空鼓判据 1.5℃
    assert err.max() > step * 5, "若最大误差反而很小,说明本用例没测到 JPEG 的真实代价"


def test_palette_shape_of_output_matches_image(tmp_path):
    """输出的温度矩阵与图片尺寸一致(后续管线依赖这个)。"""
    T = make_scene(size=(128, 96))
    path, lo, hi = _render(T, "inferno", ".png", tmp_path)
    T2 = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                     t_min=lo, t_max=hi))
    assert T2.shape == (128, 96) and T2.dtype == np.float32


def test_palette_invert_flips_temperature_direction(tmp_path):
    """invert:黑白热搞反时能把色阶方向掰回来。"""
    T = make_scene(size=(64, 64))
    path, lo, hi = _render(T, "inferno", ".png", tmp_path)
    a = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                    t_min=lo, t_max=hi))
    b = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                    t_min=lo, t_max=hi, invert=True))
    assert np.allclose(a + b, lo + hi, atol=(hi - lo) / 255 * 1.5), \
        "反色后应满足 a + b ≈ t_min + t_max"


def test_palette_wrong_colormap_gives_large_error(tmp_path):
    """**色表选错的代价**:用错的色表反演,误差会明显变大(所以先确认色表)。"""
    T = make_scene(size=(128, 128))
    path, lo, hi = _render(T, "inferno", ".png", tmp_path)
    right = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                        t_min=lo, t_max=hi))
    wrong = read_ir(path, IrCalibParams(mode="palette", colormap="rainbow",
                                        t_min=lo, t_max=hi))
    e_right = np.abs(right - T).mean()
    e_wrong = np.abs(wrong - T).mean()
    assert e_wrong > e_right * 3, \
        "错色表的误差应远大于对色表(实测 %.2f vs %.2f)" % (e_wrong, e_right)


# ---------------------------------------------------------------- matrix 模式

def test_matrix_mode_reads_npy(tmp_path):
    """npy 温度矩阵直读。"""
    T = make_scene(size=(32, 32))
    f = tmp_path / "t.npy"
    np.save(str(f), T)
    T2 = read_ir(f, IrCalibParams(mode="matrix"))
    assert np.allclose(T2, T)


def test_matrix_mode_rejects_color_image(tmp_path):
    """彩色图用 matrix 模式必须报错(否则会把 B 通道当温度,静默错得离谱)。"""
    img = np.zeros((16, 16, 3), np.uint8)
    img[:, :, 0] = 200
    f = tmp_path / "c.png"
    cv2.imwrite(str(f), img)
    with pytest.raises(ValueError) as e:
        read_ir(f, IrCalibParams(mode="matrix"))
    assert "palette" in str(e.value)


# ---------------------------------------------------------------- 色标条自采

def test_colormap_from_bar_samples_the_ramp(tmp_path):
    """从色标条采样:采到的色表应与原始色表接近。"""
    # 注意:不能用 cv2.resize 把横条"转"成竖条——resize 会得到"每行都相同的横条",
    # 采样出来是一条恒定色带。要用二维数组直接构造竖直渐变。
    ramp = np.arange(256, dtype=np.uint8).reshape(256, 1)   # 256 行 1 列 = 竖直渐变
    bar = cv2.applyColorMap(ramp, cv2.COLORMAP_INFERNO)     # (256,1,3)
    bar = np.repeat(bar, 40, axis=1)                        # 加宽成色标条
    f = tmp_path / "bar.png"
    cv2.imwrite(str(f), bar)
    refs = ir_reader.colormap_from_bar(f, n=256)
    assert refs.shape == (256, 3)
    ref_real = ir_reader._palette_refs("inferno")
    err = np.abs(refs.astype(int) - ref_real.astype(int)).mean()
    assert err < 2, "采样色表与原始色表平均每通道差 %.1f,偏大(检查边框/文字没滤掉?)" % err


def test_colormap_from_bar_rejects_blank_image(tmp_path):
    """空白图当色标条 → 明确报错,不返回一堆黑。"""
    f = tmp_path / "blank.png"
    cv2.imwrite(str(f), np.zeros((64, 16, 3), np.uint8))
    with pytest.raises(ValueError):
        ir_reader.colormap_from_bar(f)


# ---------------------------------------------------------------- 参数校验

def test_params_reject_bad_inputs():
    """三种坏参数都要报错:模式名、量程反了、色表名。"""
    with pytest.raises(ValueError) as e1:
        IrCalibParams(mode="伪彩")
    assert "mode" in str(e1.value)
    with pytest.raises(ValueError) as e2:
        IrCalibParams(mode="gray", t_min=40.0, t_max=10.0)
    assert "t_max" in str(e2.value)
    with pytest.raises(ValueError) as e3:
        IrCalibParams(mode="palette", colormap="铁红")
    assert "colormap" in str(e3.value)


def test_custom_colormap_requires_file():
    """colormap='custom' 却没给色标条路径 → 报错。"""
    with pytest.raises(ValueError) as e:
        ir_reader._palette_refs("custom", None)
    assert "palette_file" in str(e.value)


# ---------------------------------------------------------------- 与管线串联

def test_yaml_section_absent_uses_code_defaults(tmp_path):
    """defaults.yaml 里没有 ir_reader 段时用代码默认(既有文件未改,故现在就是这情况)。"""
    f = tmp_path / "c.yaml"
    f.write_text("detect:\n  z_threshold: 2.0\n", encoding="utf-8")
    assert ir_reader.from_yaml(f) == IrCalibParams()


def test_end_to_end_through_pipeline(tmp_path):
    """端到端:伪彩图 → 读取器 → **原样的 run_single** → 三类缺陷应照常检出。

    这验证了接线方式:读取器只负责翻译成 ℃,管线一行没改也照常工作。
    """
    T = make_scene()
    path, lo, hi = _render(T, "inferno", ".png", tmp_path)
    T2 = read_ir(path, IrCalibParams(mode="palette", colormap="inferno",
                                     t_min=lo, t_max=hi))
    _, defects = run_single(T2, Params())
    labels = [d.label for d in defects]
    assert "window" in labels, "窗户应检出(形状判据与标定无关)"
    assert "hollow" in labels or "seepage" in labels, "至少应检出一类真实缺陷"


# ---------------------------------------------------------------- 中文路径(Windows + OpenCV 5)

def test_reads_chinese_path(tmp_path):
    """**中文路径的图必须能读**。

    实测 OpenCV 5.0.0(Windows)的 `cv2.imread` 对非 ASCII 路径返回 None,
    本模块改用 `np.fromfile + cv2.imdecode` 绕开。既有模块(io.py / pipeline.py)
    仍在用 cv2.imread/imwrite,同样受此影响 —— 这里只保证新模块可靠。
    """
    T = make_scene(size=(64, 64))
    ascii_png, lo, hi = _render(T, "inferno", ".png", tmp_path)
    cn_dir = tmp_path / "中文目录"
    cn_dir.mkdir()
    cn_png = cn_dir / "某楼栋-南面.png"
    cn_png.write_bytes(Path(ascii_png).read_bytes())     # 复制成中文名

    T2 = read_ir(cn_png, IrCalibParams(mode="palette", colormap="inferno",
                                       t_min=lo, t_max=hi))
    assert T2.shape == (64, 64), "中文路径应能正常读出温度矩阵"


def test_imwrite_unicode_actually_writes(tmp_path):
    """**中文路径必须真的写进去** —— cv2.imwrite 会返回 True 却什么也不写。"""
    import numpy as np
    out = tmp_path / "中文输出" / "结果图.png"
    out.parent.mkdir()
    assert ir_reader._imwrite_unicode(out, np.zeros((8, 8, 3), np.uint8)) is True
    assert out.exists(), "返回 True 就必须真有文件(cv2.imwrite 在中文路径下会撒谎)"
    assert out.stat().st_size > 0
