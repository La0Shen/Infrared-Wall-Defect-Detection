"""窗形渗漏保护(window_guard)测试:纯函数判据 + 与既有管线串联 + 参数装载。

合成场景尽量复刻 test02 左柱那次的**故障机制**,而不是只摆一个"细长冷条":
一条连续均匀的细长冷条孤零零放着,闭运算块就是它自己(rect≈1.0)——而块路径
要求 rect ≤ 0.85,压根不会被收成窗户。真故障发生在**闭运算把冷条与旁边几块
独立冷碎块并成同一个块**时:块 bbox 被撑宽、rect 掉到 0.85 以下、宽高比落进
[0.15, 6.67] → 被当成窗户整块掩掉。故下面的场景都带那几块独立冷碎块。

**"边缘十分规整"这条口径用掩膜直接摆**,不在温度场上凑:合成场景的冷掩膜阈值
只有 ±0.15℃(噪声 σ=0.1),要让"缺口处比背景暖、又不进冷掩膜"根本站不住;真渗漏
那种毛边(实测 test02 左柱 fill 0.73、规整度 0.767)是真实热纹理长出来的,摆不出来。
所以锯齿条走 `_handmade()` 直接给掩膜、温度场保持干净,量到的东西单一、可解释。
**真实数据的真值另有一条用例钉住**(见文末,数据不在时自动跳过)。
"""
from pathlib import Path

import numpy as np
import pytest

from thermal_inspect import detect, preprocess, window_guard
from thermal_inspect.config import Params
from thermal_inspect.pipeline import run_single
from thermal_inspect.window_guard import GuardVerdict, WindowGuardParams


# ---------------------------------------------------------------- 场景与夹具

def _scene(strip_temp=22.0, warm=None, stripes=None):
    """背景 25℃ 噪声墙 + 34×200 连续均匀冷条 + 旁边 4 块独立冷碎块(缝隙 5px)。

    冷碎块的作用是让**闭运算块**的 bbox 撑到 48px 宽:块路径才收得下(rect 0.75、
    宽高比 0.24),而主导原始冷块仍是那根 34×200 的条(长宽比 6.0)。
    """
    rng = np.random.default_rng(7)
    T = rng.normal(25.0, 0.1, (240, 240)).astype(np.float32)
    T[20:220, 110:144] = strip_temp
    for r0 in (40, 100, 160, 200):
        T[r0:r0 + 16, 96:104] = 23.0
    if warm is not None:                      # 冷条内部一段暖色(窗格/反光)
        T[40:100, 110:144] = warm
    if stripes is not None:                   # 冷条内部条栅(窗框类强边缘)
        for r0 in (40, 120):
            T[r0:r0 + 40, 110:144] = stripes
    return T


def _prep(T, params=None):
    """按管线口径算出 judge() 需要的 (T_校正去噪, z, cold, sigma)。"""
    p = params or Params()
    T = preprocess.correct_emissivity(T, p.preprocess.emissivity,
                                      p.preprocess.reflected_temp_c)
    T = preprocess.denoise(T, p.preprocess.denoise_kernel)
    anom = detect.detrend(T, p.detect.detrend_sigma_px)
    sigma = detect.mad_sigma(anom, p.detect.mad_scale)
    z = detect.zscore(anom, sigma)
    return T, z, (z < -p.window_mask.z_threshold), sigma


def _block_mask(T, cold, close=11):
    """闭运算块掩膜(取面积最大的那个块)。"""
    import cv2
    c = cv2.morphologyEx(cold.astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((close, close), np.uint8)) > 0
    blobs = detect.extract_blobs(c, min_area=1500)
    assert blobs, "场景应产出至少一个闭运算块"
    return max(blobs, key=lambda b: b["area"])["mask"]


def _handmade(ragged: bool):
    """手摆一对场景:**同一个细长条**,一个直边、一个锯齿边(纯掩膜层面)。

    返回 (T, z, cold, block_mask)。温度场保持干净(条内 22℃、条外 25℃、内部无结构),
    这样内部两条口径都不成立,规整度是唯一变量:

        直边条:mask 就是 30×200 的矩形          → 规整度 1.000(偏离直线 0.00px)
        锯齿边:两侧交错挖 3px 深、8px 一节的长缺口 → 规整度 0.000(偏离直线 1.13px、
                超 2px 占比 0.25);缺口比腐蚀余量 4px 浅,故腐蚀后的内部仍是干净的
                条芯,不给"内部强边缘"口径送分
    """
    shape = (240, 240)
    T = np.full(shape, 25.0, np.float32)
    z = np.zeros(shape, np.float32)
    strip = np.zeros(shape, dtype=bool)
    strip[20:220, 105:135] = True                  # 30×200,长宽比 6.7
    if ragged:
        for i, r0 in enumerate(range(20, 220, 8)):  # 连续的锯齿边(节距 8px)
            if i % 2:
                strip[r0:r0 + 8, 105:108] = False   # 左侧缺口(深 3px)
            else:
                strip[r0:r0 + 8, 132:135] = False   # 右侧缺口(深 3px)
    T[strip] = 22.0
    z[strip] = -5.0
    return T, z, strip, strip


@pytest.fixture(autouse=True)
def _reset_params_cache():
    """每个用例前后都清掉模块级参数缓存。

    参数缓存是进程级的,若某个用例用 set_params 覆盖后不清,会静默污染**其它测试
    文件**里的 run_single(窗户保护被悄悄关掉)。故前后各清一次。
    """
    window_guard.set_params(None)
    yield
    window_guard.set_params(None)


# ---------------------------------------------------------------- 纯函数层

def test_regular_elongated_strip_is_window():
    """口径③(边缘十分规整):直边细长冷条 → 也视为窗户,不释放。

    显式传代码默认参数:defaults.yaml 是现场随手调的落点(口径开关可能被关掉),
    本用例测的是判据本身,不是那份配置。
    """
    T, z, cold, block = _handmade(ragged=False)
    v = window_guard.judge(T, z, cold, block, 0.1, gp=WindowGuardParams())
    assert v.triggered and v.elong > 5.0
    assert v.regularity >= WindowGuardParams().regular_min, \
        "直边条的规整度应接近 1(实测 %.3f)" % v.regularity
    assert v.warm_frac <= 0.10 and v.edge_frac <= 0.005, "另两条口径都不该成立(单一变量)"
    assert v.is_window, "边缘规整 → 视为窗户"
    assert "规整" in v.reason


def test_ragged_elongated_strip_is_not_window():
    """边缘毛糙(规整度低于门槛)+ 内部均衡 → 不是窗户(按渗漏输出)。"""
    T, z, cold, block = _handmade(ragged=True)
    v = window_guard.judge(T, z, cold, block, 0.1, gp=WindowGuardParams())
    assert v.triggered and v.elong > 5.0
    assert v.regularity < WindowGuardParams().regular_min, \
        "锯齿边的规整度应低于门槛(实测 %.3f)" % v.regularity
    assert v.warm_frac <= 0.10 and v.edge_frac <= 0.005, "内部口径不该被锯齿带偏"
    assert not v.is_window, "边缘毛糙 + 内部均衡 → 不是窗户"
    assert v.component is not None and v.bbox is not None, "释放时要带上真实物体"
    assert v.bbox[2] < 40, "释放的物体应是那根条本身"


def test_regular_switch_off_releases():
    """口径③开关关掉:同一条直边条随即被释放(门槛不动,只关开关)。"""
    T, z, cold, block = _handmade(ragged=False)
    gp = WindowGuardParams(regular_on=False)
    v = window_guard.judge(T, z, cold, block, 0.1, gp=gp)
    assert v.regularity <= 1.0, "指标照算(规整度上限就是 1.0,已夹住)"
    assert not v.is_window, "口径③关掉后,直边条也会被释放"
    assert "口径关闭" in v.reason, "理由里要写明这条口径是关着的"


def test_all_channels_off_releases_everything_elongated():
    """三条口径全关 = 只剩 elong_min 一道门:狭长 + 内部均衡的块一律释放。"""
    T, z, cold, block = _handmade(ragged=False)
    gp = WindowGuardParams(warm_on=False, edge_on=False, regular_on=False)
    assert not window_guard.judge(T, z, cold, block, 0.1, gp=gp).is_window
    T2, z2, cold2, block2 = _handmade(ragged=True)
    assert not window_guard.judge(T2, z2, cold2, block2, 0.1, gp=gp).is_window


def test_yaml_switch_written_as_01(tmp_path):
    """开关在 YAML 里写成 0/1 也认(与 display 段同口径);写成别的值必须报错。"""
    f = tmp_path / "c.yaml"
    f.write_text("window_guard:\n  regular_on: 0\n  warm_on: 1\n", encoding="utf-8")
    gp = window_guard.from_yaml(f)
    assert gp.regular_on is False and gp.warm_on is True and gp.edge_on is True

    bad = tmp_path / "bad.yaml"
    bad.write_text("window_guard:\n  edge_on: ture\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        window_guard.from_yaml(bad)
    assert "edge_on" in str(e.value)


def test_regularity_metric_values():
    """规整度的两个原始量:偏离拟合直线的平均 px、超容差的突出占比。"""
    gp = WindowGuardParams()
    shape = (160, 160)
    rect = np.zeros(shape, dtype=bool)
    rect[10:150, 70:90] = True                     # 20×140 的完美矩形
    d = window_guard.edge_fit_detail(rect, gp.edge_tol_px)
    assert d["dev_px"] < 1e-9, "直边的上下沿应贴合拟合直线(实测 %.3f)" % d["dev_px"]
    assert d["prot_frac"] == 0.0
    assert window_guard.regularity(rect, gp.edge_dev_ref_px, gp.edge_tol_px) > 0.999, "直边无突出 → 规整度满分"

    ragged = rect.copy()
    for i, r0 in enumerate(range(14, 146, 8)):     # 两侧交错挖 4px 深缺口
        if i % 2:
            ragged[r0:r0 + 4, 70:74] = False
        else:
            ragged[r0:r0 + 4, 86:90] = False
    d2 = window_guard.edge_fit_detail(ragged, gp.edge_tol_px)
    assert d2["dev_px"] > 0.3, "毛边应明显偏离直线(实测 %.2fpx)" % d2["dev_px"]
    assert d2["prot_frac"] > 0.0, "应量出突出的占比"
    assert window_guard.regularity(ragged, gp.edge_dev_ref_px, gp.edge_tol_px) < WindowGuardParams().regular_min,         "毛边 + 突出 → 规整度低于门槛(实测 %.3f)" % window_guard.regularity(ragged, gp.edge_dev_ref_px, gp.edge_tol_px)

    assert window_guard.regularity(np.zeros(shape, dtype=bool)) == 0.0, "空掩膜不崩"


def test_regularity_uses_long_edges_not_size():
    """口径只看"边直不直",与物体多大无关:同一个锯齿比例,宽的窄的一样判。"""
    gp = WindowGuardParams()
    out = []
    for width in (12, 60):
        m = np.zeros((300, 300), dtype=bool)
        m[20:280, 100:100 + width] = True
        for i, r0 in enumerate(range(24, 276, 16)):     # 深度固定 4px 的锯齿
            if i % 2:
                m[r0:r0 + 8, 100:104] = False
            else:
                m[r0:r0 + 8, 100 + width - 4:100 + width] = False
        out.append(window_guard.regularity(m, gp.edge_dev_ref_px, gp.edge_tol_px))
    assert abs(out[0] - out[1]) < 0.02, "宽窄只该差在分箱细节上(实测 %s)" % out
    assert max(out) < WindowGuardParams().regular_min, "锯齿一样密,宽窄都该判不规整"


def test_cylindrical_contour_sanity():
    """口径③只对"极端狭长"的物体生效:圆盘这类光滑但不直边的东西,长宽比过不了门槛。"""
    yy, xx = np.mgrid[0:120, 0:120]
    disc = ((xx - 60) ** 2 + (yy - 60) ** 2) < 40 ** 2
    T = np.full((120, 120), 25.0, np.float32)
    z = np.zeros((120, 120), np.float32)
    T[disc], z[disc] = 22.0, -5.0
    v = window_guard.judge(T, z, disc, disc, 0.1)
    assert not v.triggered, "圆盘长宽比≈1,不进判据(整条保护只管极端狭长的物体)"


def test_inner_warm_structure_keeps_window():
    """内部有明显更暖的子结构(口径①)→ 仍按窗户。

    另两条口径关掉再判:合成场景的冷掩膜是干净矩形,规整度天然≈1.0,**不关就会
    被口径③顺带救下**,这条用例也就测不到口径①了。
    """
    T = _scene()
    T, z, cold, sigma = _prep(T)
    m = _block_mask(T, cold)
    x, y, w, h = window_guard.largest_cold_component(m, cold)[1]
    z = z.copy()
    z[y:y + h, x:x + w] = -1.0                 # 抹平冷条本身
    z[y + 10:y + 40, x:x + w] = 5.0            # 塞进一段"暖子结构"(z=+5 > warm_z)
    v = window_guard.judge(T, z, cold, m, sigma,
                           gp=WindowGuardParams(edge_on=False, regular_on=False))
    assert v.triggered and v.warm_frac > 0.10, "暖像素占比应超过上限"
    assert v.is_window, "有暖子结构的狭长块仍按窗户(口径①)"


def test_warm_switch_off_lets_it_through():
    """口径①开关关掉:同一个"内部有暖子结构"的块随即被释放。"""
    T = _scene()
    T, z, cold, sigma = _prep(T)
    m = _block_mask(T, cold)
    x, y, w, h = window_guard.largest_cold_component(m, cold)[1]
    z = z.copy()
    z[y:y + h, x:x + w] = -1.0
    z[y + 10:y + 40, x:x + w] = 5.0
    v = window_guard.judge(T, z, cold, m, sigma,
                           gp=WindowGuardParams(warm_on=False, regular_on=False))
    assert not v.is_window, "口径①关掉后,该块不再被它拦下"


def test_inner_edges_keep_window():
    """内部有窗框类强边缘(口径②)→ 仍按窗户(同样要关掉口径③才测得到②)。"""
    T = _scene(stripes=23.6)
    T, z, cold, sigma = _prep(T)
    v = window_guard.judge(T, z, cold, _block_mask(T, cold), sigma,
                           gp=WindowGuardParams(warm_on=False, regular_on=False))
    assert v.triggered
    assert v.edge_frac > 0.005, "内部条栅应量出强边缘(实测 %.4f)" % v.edge_frac
    assert v.is_window, "内部有结构的狭长块仍按窗户(口径②)"


def test_edge_switch_off_lets_it_through():
    """口径②开关关掉:同一条带条栅的块随即被释放。"""
    T = _scene(stripes=23.6)
    T, z, cold, sigma = _prep(T)
    v = window_guard.judge(T, z, cold, _block_mask(T, cold), sigma,
                           gp=WindowGuardParams(warm_on=False, edge_on=False,
                                                regular_on=False))
    assert not v.is_window, "口径②关掉后,该块不再被它拦下"


def test_compact_block_not_triggered():
    """不狭长的块不进判据(长宽比 < elong_min),沿用原判。"""
    rng = np.random.default_rng(11)
    T = rng.normal(25.0, 0.1, (160, 160)).astype(np.float32)
    T[60:100, 60:100] = 22.0                   # 40×40 方块,长宽比 1
    T, z, cold, sigma = _prep(T)
    v = window_guard.judge(T, z, cold, _block_mask(T, cold, close=3), sigma)
    assert not v.triggered and v.is_window


def test_disabled_is_noop():
    """enabled=False 时完全不动(恢复旧行为)。"""
    T = _scene()
    T, z, cold, sigma = _prep(T)
    v = window_guard.judge(T, z, cold, _block_mask(T, cold), sigma,
                           gp=WindowGuardParams(enabled=False))
    assert not v.triggered and v.is_window


def test_elong_min_is_the_knob():
    """elong_min 抬高到冷条长宽比之上 → 不触发。"""
    T = _scene()
    T, z, cold, sigma = _prep(T)
    m = _block_mask(T, cold)
    v = window_guard.judge(T, z, cold, m, sigma,
                           gp=WindowGuardParams(elong_min=12.0))
    assert not v.triggered and v.is_window


def test_block_without_raw_cold_pixels_not_triggered():
    """块内没有原始冷像素(纯闭运算合成)→ 不触发,沿用原判。"""
    T = _scene()
    T, z, cold, sigma = _prep(T)
    block = np.zeros(T.shape, dtype=bool)
    block[30:60, 30:60] = True                 # 全是闭运算合成的块,冷掩膜里没有它
    v = window_guard.judge(T, z, cold, block, sigma)
    assert not v.triggered and v.is_window
    assert "原始冷像素" in v.reason


def test_tiny_component_not_triggered():
    """主导冷块过小 → 不触发(形状/统计都不可靠)。"""
    T = _scene()
    T, z, cold, sigma = _prep(T)
    block = np.zeros(T.shape, dtype=bool)
    block[20:80, 130:134] = True               # 4×60 细条,面积 240 < 阈值 200?不,用更小
    block[20:40, 130:134] = True
    cold_small = np.zeros(T.shape, dtype=bool)
    cold_small[20:40, 130:134] = True
    v = window_guard.judge(T, z, cold_small, block, sigma)
    assert not v.triggered and v.is_window


def test_largest_component_is_judged():
    """块内有多块原始冷像素时,判的是面积最大那块。"""
    T = _scene()
    T, z, cold, sigma = _prep(T)
    m = _block_mask(T, cold)
    comp, bbox, area = window_guard.largest_cold_component(m, cold)
    assert comp is not None and area > 5000, "应取到那根大冷条"
    assert bbox[3] > bbox[2] * 4, "取到的应是细长的那块(高 >> 宽)"


def test_elongation_matches_features_convention():
    """长宽比与 features.elong **完全同口径**(同一个最小外接矩形公式)。

    不写死 6.0:OpenCV 的 minAreaRect 在 60×10 这种小图上给出 61×11 或 59×9 之类的
    结果(取决于旋转卡壳的实现),写死数值会把"口径一致"这件事测成"OpenCV 的版本号"。
    直接与 features 比同一个量。
    """
    from thermal_inspect import features as feat_mod
    T = np.full((80, 80), 25.0, np.float32)
    m = np.zeros((80, 80), dtype=bool)
    m[10:70, 30:40] = True                     # 细长竖条
    f = feat_mod.extract_features(m, T, bbox=(30, 10, 10, 60))
    assert abs(window_guard.elongation(m) - f["elong"]) < 1e-9
    assert f["elong"] > 5.0


# ---------------------------------------------------------------- 与管线串联

def test_regular_strip_stays_window_through_pipeline():
    """端到端(默认参数):直边均匀的细长冷条被口径③拦下,仍是窗户。

    这就是用户追加这条通道要的效果——"长直边的带子"更像带窗,不像渗水。
    """
    window_guard.set_params(WindowGuardParams())     # 代码默认(口径③开)
    _, defects = run_single(_scene(), Params())
    labels = [d.label for d in defects]
    assert "window" in labels, "边缘规整的狭长块应保持窗户"
    assert "seepage" not in labels


def test_release_path_still_works_through_pipeline():
    """端到端(口径③关掉):同一条直边冷条随即按渗漏报出。

    释放这条路(窗户掩膜 → 保护 → label=seepage → 几何取真实物体)在 J 节是为
    test02 左柱建的,不能因为新通道就没人跑了。合成场景摆不出真渗漏那种毛边,
    故这里关掉口径③来打通这条路;真实毛边的真值另有用例钉(见文末)。
    """
    window_guard.set_params(WindowGuardParams(regular_on=False))
    _, defects = run_single(_scene(), Params())
    labels = [d.label for d in defects]
    assert "seepage" in labels, "口径③关掉后,均匀狭长冷条应按渗漏报出"
    assert "window" not in labels, "它不应再被当成窗户"
    seep = [d for d in defects if d.label == "seepage"][0]
    assert seep.sign == "cold"
    assert seep.bbox[2] < 40, "报出的几何应是那根 34px 宽的冷条本身"


def test_guard_disabled_restores_old_window_judgement():
    """关闭保护:同一场景回到旧行为(窗户)。"""
    window_guard.set_params(WindowGuardParams(enabled=False))
    _, defects = run_single(_scene(), Params())
    labels = [d.label for d in defects]
    assert "window" in labels and "seepage" not in labels


def test_strip_with_inner_edges_stays_window_through_pipeline():
    """内部有窗框类条栅的狭长块,经管线仍是窗户(口径②;锯齿边也不该把它送出去)。"""
    _, defects = run_single(_scene(stripes=23.6), Params())
    labels = [d.label for d in defects]
    assert "window" in labels
    assert "seepage" not in labels


def test_temperature_matrix_unchanged_by_guard():
    """保护只改标签,不改"移出净墙"这件事:温度矩阵与关闭保护时逐像素一致。"""
    T = _scene()
    window_guard.set_params(WindowGuardParams(enabled=False))
    T_off, _ = run_single(T, Params())
    window_guard.set_params(WindowGuardParams(regular_on=False))  # 走释放那条路
    T_on, _ = run_single(T, Params())
    assert np.array_equal(T_on, T_off), "修复后的温度矩阵应与关保护时完全一致"


def test_verdict_defaults():
    """GuardVerdict 的惰性默认值(未触发时调用方只需读 is_window/triggered)。"""
    v = GuardVerdict(is_window=True, triggered=False)
    assert v.elong == 0.0 and v.regularity == 0.0
    assert v.component is None and v.bbox is None


# ---------------------------------------------------------------- 参数装载

def test_params_from_defaults_yaml_parses_with_right_types():
    """defaults.yaml 的 window_guard 段必须能通过严格校验,**但不冻结具体取值**。

    那一段是现场随手调的落点(与 tests/test_config.py 的 test_defaults_yaml_loads
    同一口径):要钉"出厂默认",钉在代码默认 `WindowGuardParams()` 上,别钉在这份
    YAML 上——否则用户一调参(比如关掉某条口径)用例就变红,而配置本身完全合法。
    """
    from pathlib import Path
    p = window_guard.from_yaml(Path(__file__).resolve().parents[1]
                               / "config" / "defaults.yaml")
    assert isinstance(p, WindowGuardParams)
    for name in ("enabled", "warm_on", "edge_on", "regular_on"):
        assert isinstance(getattr(p, name), bool), name
    for name in ("elong_min", "warm_z", "warm_frac_max", "edge_k", "edge_frac_max",
                 "regular_min", "edge_dev_ref_px", "edge_tol_px"):
        assert isinstance(getattr(p, name), float), name


def test_params_missing_section_uses_code_defaults(tmp_path):
    """YAML 里没有该段时用代码默认(不报错)。"""
    f = tmp_path / "c.yaml"
    f.write_text("detect:\n  z_threshold: 2.0\n", encoding="utf-8")
    assert window_guard.from_yaml(f) == WindowGuardParams()


def test_params_unknown_key_raises(tmp_path):
    """键名写错必须报错,不静默回退默认。"""
    f = tmp_path / "c.yaml"
    f.write_text("window_guard:\n  elong_mim: 3.0\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        window_guard.from_yaml(f)
    assert "elong_mim" in str(e.value)


def test_params_switches_accept_bool_and_01():
    """四个开关(enabled + 三条口径)都认 true/false 与 YAML 里常见的 0/1;
    别的值报错、报错里带键名(不静默当真)。"""
    assert WindowGuardParams(enabled=True).enabled is True
    assert WindowGuardParams(enabled=0).enabled is False
    assert WindowGuardParams(enabled=1).enabled is True
    for name in ("warm_on", "edge_on", "regular_on"):
        assert getattr(WindowGuardParams(**{name: 1}), name) is True
        assert getattr(WindowGuardParams(**{name: 0}), name) is False
        with pytest.raises(ValueError) as e:
            WindowGuardParams(**{name: "ture"})
        assert name in str(e.value)
    with pytest.raises(ValueError):
        WindowGuardParams(enabled="ture")


def test_set_params_overrides_and_cache_reset():
    """set_params 立即生效;None 清缓存,恢复按文件装载。"""
    gp = WindowGuardParams(elong_min=9.9)
    window_guard.set_params(gp)
    assert window_guard.current_params() is gp
    window_guard.set_params(None)
    assert window_guard.current_params() == window_guard.from_yaml(
        window_guard.default_yaml_path()), "清缓存后应回到'按文件装载'那条路"


# ---------------------------------------------------------------- 真实帧真值(数据不入库)

_REAL = Path(__file__).resolve().parents[1] / "data" / "raw" / "test02.JPG"


@pytest.mark.skipif(not _REAL.exists(), reason="真实帧 test02.JPG 不在(data/raw 不入库)")
def test_real_frame_test02_strip_is_seepage():
    """真值钉住(test02):左侧贯穿全高的竖直冷条要报成渗漏,不是窗户。

    这就是 J 节那次修复的本体,也是"边缘规整"这条通道的哨兵——它**不能把真渗漏
    救回成窗户**(实测该条规整度 0.767 < 门槛 0.85)。真实数据不入库
    (`.gitignore` 排除 `data/raw`),数据不在时跳过;有数据时必须过。
    """
    from thermal_inspect.io import read_temperature
    p = Params.from_yaml(Path(__file__).resolve().parents[1] / "config" / "defaults.yaml")
    _, defects = run_single(read_temperature(_REAL), p)
    seep = [d for d in defects
            if d.label == "seepage" and d.bbox[2] < 60 and d.bbox[3] > 300]
    assert seep, "test02 左柱应报成渗漏"
    assert not [d for d in defects if d.label == "window" and d.bbox[0] < 60], \
        "左柱不该再是窗户"
