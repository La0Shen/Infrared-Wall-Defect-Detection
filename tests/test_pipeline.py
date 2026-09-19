"""端到端测试:合成温度图应检出空鼓、渗水、窗户三类目标。"""
import json

import cv2
import numpy as np

from thermal_inspect.config import Params
from thermal_inspect.demo import make_scene
from thermal_inspect.pipeline import render_overlay, run_single, save_results


def test_end_to_end():
    T = make_scene()
    T2, defects = run_single(T, Params())
    assert T2.shape == T.shape, "run_single 应返回校正后的温度矩阵"
    labels = [d.label for d in defects]
    assert "hollow" in labels, "应检出空鼓"
    assert "seepage" in labels, "应检出渗水"
    assert "window" in labels, "应检出窗户"

    # 空鼓:热斑,位于植入位置附近
    hollow = [d for d in defects if d.label == "hollow"]
    assert all(d.sign == "warm" for d in hollow)
    assert any(100 <= d.bbox[0] <= 180 and 120 <= d.bbox[1] <= 200 for d in hollow), \
        "空鼓斑块应位于植入位置(140,160)附近"

    # 渗水:冷斑,细长,位于植入位置附近
    seep = [d for d in defects if d.label == "seepage"]
    assert all(d.sign == "cold" for d in seep)
    assert any(abs(d.bbox[0] - 350) <= 30 for d in seep), "渗水斑块应位于植入位置(x≈350)附近"

    # 窗户:冷斑,面积最大,位于植入位置附近
    win = [d for d in defects if d.label == "window"]
    assert len(win) == 1
    assert win[0].sign == "cold"
    assert win[0].area_px > 5000
    assert abs(win[0].bbox[0] - 400) <= 10 and abs(win[0].bbox[1] - 330) <= 10


def test_physical_area_with_distance():
    """填写拍摄距离后输出物理面积。"""
    T = make_scene()
    p = Params()
    p.preprocess.distance_m = 10.0  # GSD = 10/540 ≈ 0.0185 m/px
    T2, defects = run_single(T, p)
    assert T2.shape == T.shape
    win = [d for d in defects if d.label == "window"][0]
    assert win.area_m2 is not None
    assert abs(win.area_m2 - win.area_px * (10.0 / 540.0) ** 2) < 1e-9


def test_run_single_flat_frame_zero_defects():
    """平坦帧:噪声估计退化 → 不做异常判定,零缺陷(不再全图误报)。"""
    T, defects = run_single(np.full((64, 64), 25.0, np.float32), Params())
    assert defects == []
    assert np.all(T == T.flat[0])  # 校正后的温度矩阵(发射率校正后仍平坦)


# ---------------------------------------------------------------- 窗户掩膜

def _add_disc(T, cx, cy, r, val):
    """在温度图上画一个圆形温度斑块(圆斑最小外接矩形度≈0.78,可判 hollow)。"""
    yy, xx = np.mgrid[0:T.shape[0], 0:T.shape[1]]
    m = (xx - cx) ** 2 + (yy - cy) ** 2 < r ** 2
    T[m] = val
    return m


def _add_gauss_bump(T, cx, cy, r, amp):
    """高斯弥散暖斑(空鼓形态:软边界大直径,rect<0.8 可判 hollow)。

    注意 r=8 的数字硬边圆斑 minAreaRect 会内切成方形,rect≈0.92 反被判
    reject;要得到稳定的 hollow 需用弥散大斑,与 demo 场景一致。
    """
    yy, xx = np.mgrid[0:T.shape[0], 0:T.shape[1]]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    T += (amp * np.exp(-(d ** 2) / (2 * (r / 1.6) ** 2))).astype(np.float32)


def _scene_with_window():
    """200×200 合成墙:冷矩形窗(90×70)+ 窗内暖斑 + 窗间墙暖斑。"""
    rng = np.random.default_rng(42)
    T = rng.normal(25.0, 0.1, (200, 200)).astype(np.float32)
    T[60:130, 50:140] = 18.0                       # 窗户:冷矩形
    T[80:100, 90:110] = 25.0                       # 窗内暖斑(反光)
    _add_disc(T, 37.5, 47.5, 8.0, 30.0)            # 窗间墙圆形暖斑(真缺陷候选)
    return T


def test_window_mask_excludes_inside_blobs():
    """窗户掩膜:窗户报出,窗内暖斑被排除,窗间墙暖斑保留。"""
    T, defects = run_single(_scene_with_window(), Params())
    labels = [d.label for d in defects]
    assert "window" in labels, "窗户应报出"
    win_rect = (50, 60, 90, 70)
    for d in defects:
        if d.label == "window":
            continue
        x, y, w, h = d.bbox
        inside = x >= win_rect[0] and y >= win_rect[1] and \
            x + w <= win_rect[0] + win_rect[2] and y + h <= win_rect[1] + win_rect[3]
        assert not inside, "窗户区域内不应有非 window 缺陷: %s %s" % (d.label, d.bbox)
    # 窗间墙暖斑应保留(断言暖斑本体未被掩掉、仍在缺陷列表中;类别由分类层
    # 决定——r=8 数字圆斑 rect≈0.92,本判 reject,旧版 Telea 填充棋盘纹恰被
    # 误判 hollow 掩盖了这一点)
    assert any(d.sign == "warm" and d.bbox[0] <= 37.5 <= d.bbox[0] + d.bbox[2]
               and d.bbox[1] <= 47.5 <= d.bbox[1] + d.bbox[3] for d in defects), \
        "窗间墙暖斑应保留(未被掩膜排除)"


def test_window_mask_spares_seepage():
    """细长冷条(渗水)不得被窗户掩膜误掩。

    本用例摆的是**理想矩形**冷条(合成场景摆不出毛边,见 test_window_guard 的说明),
    会被"渗漏保护"按人造直边物改判 —— 故显式关掉它:这里测的是窗户掩膜,不是渗漏分类。
    """
    from thermal_inspect import seepage_guard
    from thermal_inspect.seepage_guard import SeepageGuardParams
    seepage_guard.set_params(SeepageGuardParams(enabled=False))
    rng = np.random.default_rng(43)
    T = rng.normal(25.0, 0.1, (200, 200)).astype(np.float32)
    T[40:180, 95:107] = 22.0                       # 12×140 细长冷条,宽高比 0.086
    try:
        _, defects = run_single(T, Params())
        assert "seepage" in [d.label for d in defects], "渗水细条不应被掩掉"
        assert "window" not in [d.label for d in defects]
    finally:
        seepage_guard.set_params(None)


def test_window_mask_block():
    """窗户群合并成的参差区域块(test01 左柱形态):被掩,块内斑块排除。"""
    rng = np.random.default_rng(44)
    T = rng.normal(25.0, 0.1, (240, 240)).astype(np.float32)
    # 三段错位窗扇(8px 缝隙,闭运算合并成参差块 rect≈0.63、宽高比 0.21)
    T[20:60, 80:100] = 21.0
    T[68:108, 88:108] = 21.0
    T[116:156, 84:104] = 21.0
    T[30:40, 90:98] = 28.0                          # 块内暖斑(反光)
    _add_disc(T, 200.0, 60.0, 14.0, 32.0)           # 块外圆形暖斑(远离冷块,避开去趋势光晕)
    _, defects = run_single(T, Params())
    labels = [d.label for d in defects]
    assert "window" in labels, "窗户区域块应报出 window"
    for d in defects:
        if d.label == "window":
            continue
        x, y, w, h = d.bbox
        in_block = x >= 80 and y >= 20 and x + w <= 108 and y + h <= 156
        assert not in_block, "块内不应有非 window 缺陷: %s %s" % (d.label, d.bbox)
    # 掩膜契约:块外斑块不被排除,仍出现在缺陷列表中(类别由分类层决定)
    assert any(d.label != "window"
               and d.bbox[0] <= 200 <= d.bbox[0] + d.bbox[2]
               and d.bbox[1] <= 60 <= d.bbox[1] + d.bbox[3]
               for d in defects), "块外暖斑应保留在缺陷列表中(未被掩膜排除)"


def test_window_mask_disabled_restores_old():
    """window_mask.enabled=false:恢复旧行为(不排除、不报出区域块)。"""
    p = Params()
    p.window_mask.enabled = False
    T, defects = run_single(_scene_with_window(), p)
    # 旧行为下窗户本身由 window 规则(dT<−5)报出,窗内暖斑按正常分类处理
    assert "window" in [d.label for d in defects]


def test_window_deletion_covers_transition():
    """软边窗户(高斯过渡带):删除后窗户与过渡带都应恢复到背景水平。

    固定 dilate_px 只膨胀 2px,盖不住去噪/导热造成的渐变带(修复后残留
    一圈过渡环);自适应生长应把过渡带一并纳入掩膜并填回背景,第二遍
    检测不产生窗边伪缺陷,远处暖斑不被吞掉。
    """
    rng = np.random.default_rng(45)
    T = rng.normal(25.0, 0.1, (200, 200)).astype(np.float32)
    win = np.zeros((200, 200), dtype=bool)
    win[60:130, 50:140] = True
    soft = cv2.GaussianBlur(win.astype(np.float32), (0, 0), 3.0)   # 过渡带 ≈ ±9px
    T = T * (1.0 - soft) + 18.0 * soft
    _add_gauss_bump(T, 170.0, 170.0, 16.0, 5.0)      # 远处空鼓:生长不得吞掉
    T2, defects = run_single(T, Params())
    assert "window" in [d.label for d in defects], "窗户应报出"
    med = float(np.median(T2))
    # 窗本体应填回背景
    assert abs(float(np.median(T2[win])) - med) < 0.5, \
        "窗本体应填回背景温度,实际偏差 %.2f℃" % (float(np.median(T2[win])) - med)
    # 过渡带(d∈(4,8],原为 22~25℃ 渐变区)应填回背景
    d = cv2.distanceTransform(win.astype(np.uint8), cv2.DIST_L2, 3)
    ring = (d > 4) & (d <= 8)
    residual = abs(float(np.median(T2[ring])) - med)
    assert residual < 0.35, "过渡带应填回背景,实际残留 %.2f℃" % residual
    # 判别力:关闭自适应生长(仅 dilate_px)时残留应明显更大
    p_old = Params()
    p_old.window_mask.grow_max_px = 0
    T2_old, _ = run_single(T, p_old)
    med_old = float(np.median(T2_old))
    residual_old = abs(float(np.median(T2_old[ring])) - med_old)
    assert residual_old > residual + 0.1, \
        "自适应生长应吃掉更多过渡带(新 %.2f℃ vs 旧 %.2f℃)" % (residual, residual_old)
    # 第二遍检测:窗内+过渡带内不得出现有意义类别的缺陷(hollow/seepage/
    # window);reject 为过渡带角部残留的零点几度噪声级冷缝,允许存在
    # (其贴边者已被 exclude_overlap 排除,其余低于可见阈值)
    for df in defects:
        if df.label == "window":
            continue
        x, y, w, h = df.bbox
        in_win = x >= 40 and y >= 50 and x + w <= 150 and y + h <= 140
        assert not (in_win and df.label != "reject"), \
            "窗+过渡带内不应有非 reject 缺陷: %s %s" % (df.label, df.bbox)
    # 远处空鼓应保留(断言暖斑本体未被生长吞掉;类别由分类层决定——此处
    # 斑块受窗口去趋势光晕影响 rect≈0.82 略超 hollow_rect=0.8,判 reject)
    assert any(df.sign == "warm" and df.bbox[0] <= 170 <= df.bbox[0] + df.bbox[2]
               and df.bbox[1] <= 170 <= df.bbox[1] + df.bbox[3] for df in defects), \
        "远处空鼓应保留(未被生长吞掉)"


# ---------------------------------------------------------------- 叠加图显示过滤

# render_overlay 的 colors:窗口青、空鼓红、渗水蓝、reject 白(BGR)
_COLORS = {"window": (0, 255, 255), "hollow": (0, 0, 255),
           "seepage": (255, 0, 0), "reject": (255, 255, 255)}


def _count_color(img, bgr):
    """图中完全等于该 BGR 的像素数(INFERNO 伪彩不含青/纯蓝/纯红/纯白,
    故这些颜色只可能来自轮廓与标签)。"""
    return int((img == np.array(bgr, np.uint8)).all(axis=-1).sum())


def test_render_overlay_default_matches_no_filter():
    """不传 disp 与传默认 DisplayParams 必须逐像素一致:默认行为零变更。"""
    T, defects = run_single(_scene_with_window(), Params())
    assert np.array_equal(render_overlay(T, defects),
                          render_overlay(T, defects, Params().display))


def test_overlay_flag_hides_its_class():
    """show_window=0 后窗户不再绘制,其余类别不受影响。"""
    T, defects = run_single(_scene_with_window(), Params())
    base = render_overlay(T, defects, Params().display)
    assert _count_color(base, _COLORS["window"]) > 0, "默认应画出窗户轮廓"
    disp = Params().display
    disp.show_window = 0
    hidden = render_overlay(T, defects, disp)
    assert _count_color(hidden, _COLORS["window"]) == 0, "窗户不应再被绘制"
    # 其他类别:只断言"仍有像素",不做相等——不同类别的轮廓与标签像素会重叠
    for label, bgr in _COLORS.items():
        if label != "window" and _count_color(base, bgr) > 0:
            assert _count_color(hidden, bgr) > 0, "%s 不应被误伤" % label


def test_overlay_min_len_boundary_includes_equal():
    """min_len 含等号:长边 == 阈值仍显示,大 1px 即隐藏。"""
    T, defects = run_single(_scene_with_window(), Params())
    win = [d for d in defects if d.label == "window"][0]
    L = max(win.bbox[2], win.bbox[3])
    disp_eq = Params().display
    disp_eq.min_len_window_px = L
    disp_gt = Params().display
    disp_gt.min_len_window_px = L + 1
    assert _count_color(render_overlay(T, defects, disp_eq), _COLORS["window"]) > 0
    assert _count_color(render_overlay(T, defects, disp_gt), _COLORS["window"]) == 0


def test_save_results_filters_overlay_but_keeps_other_outputs_full(tmp_path):
    """验收用例:display 段只影响 overlay.png。

    CSV / summary(含 counts)/ mask 文件必须保持全量;同时验证
    save_results 确实把 params.display 透传给了 render_overlay
    (漏传时 overlay 不变、其余全绿,是典型的静默失败)。
    """
    T, defects = run_single(_scene_with_window(), Params())
    p = Params()
    for name in ("show_window", "show_hollow", "show_seepage", "show_reject"):
        setattr(p.display, name, 0)          # 全部关掉
    out = save_results(tmp_path, "case", T, defects, p, scheme="single")

    # overlay 已按 display 过滤
    got = cv2.imread(str(out / "overlay.png"))
    assert np.array_equal(got, render_overlay(T, defects, p.display))
    assert not np.array_equal(got, render_overlay(T, defects, Params().display)), \
        "四个开关全关后 overlay 应与默认渲染不同(否则 display 未生效)"

    # 其余输出保持全量
    rows = (out / "defects.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(rows) - 1 == len(defects), "defects.csv 应保持全量"
    assert len(list(out.glob("mask_*.png"))) == len(defects), "mask 应保持全量"
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert sum(s["counts"].values()) == len(defects), "counts 应保持全量"
    assert len(s["defects"]) == len(defects), "summary.defects 应保持全量"
    assert s["params"]["display"]["show_hollow"] == 0, "参数快照应含 display 段"


def test_overlay_numbering_keeps_csv_index():
    """编号契约:隐藏后编号不重排,仍等于斑块在列表中的下标。

    用只留一个斑块可见的配置,断言图上画的编号与该斑块的原下标一致。
    """
    T, defects = run_single(_scene_with_window(), Params())
    target = next(i for i, d in enumerate(defects) if d.label == "window")
    p = Params()
    for name in ("show_window", "show_hollow", "show_seepage", "show_reject"):
        setattr(p.display, name, 0)
    p.display.show_window = 1
    shown = [i for i, d in enumerate(defects) if p.display.shows(d.label, d.bbox)]
    assert shown == [target], "只应剩窗户可见"
    # 只画一个斑块时,图上应能找到该原下标的标签文本
    assert _count_color(render_overlay(T, defects, p.display), _COLORS["window"]) > 0


# ---------------------------------------------------------------- 边界带

def _scene_with_edge_blobs():
    """200×200 合成墙:左边缘一块冷斑(在边界带内)+ 内部一块冷斑。"""
    rng = np.random.default_rng(77)
    T = rng.normal(25.0, 0.1, (200, 200)).astype(np.float32)
    T[80:130, 0:9] = 18.0        # 左边缘冷斑:band=15 时应被剔
    T[80:130, 60:69] = 18.0      # 内部同尺寸冷斑:应保留
    return T


def test_border_band_drops_edge_blobs_keeps_interior():
    """边界带=墙:完全落在带内的斑块不再报出,内部斑块不受影响。

    注意"边界带"是**检测口径**而非形状口径:足够的像素落在带内才会被检出,
    但一旦检出,报出的是它所属完整连通域的形状(见下一个用例)。
    这里两块都完全位于带内/内部,所以不存在回查。
    """
    T = _scene_with_edge_blobs()

    off = Params()
    off.detect.border_ignore_px = 0
    _, defects_off = run_single(T, off)
    edge_off = [d for d in defects_off if d.sign == "cold" and d.bbox[0] < 15]
    assert edge_off, "关闭边界带时应报出贴边冷斑"

    on = Params()
    on.detect.border_ignore_px = 15
    _, defects_on = run_single(T, on)
    assert not [d for d in defects_on if d.sign == "cold" and d.bbox[0] < 15], \
        "完全落在边界带内的冷斑不应报出"
    # 内部同尺寸冷斑仍在
    assert any(d.sign == "cold" and d.bbox[0] <= 64 <= d.bbox[0] + d.bbox[2]
               for d in defects_on), "内部冷斑应保留"


def _scene_border_shape():
    """200×200:一条贯穿全高的细长冷条(上下都跑出画面)+ 一块右侧贴边冷块。"""
    rng = np.random.default_rng(91)
    T = rng.normal(25.0, 0.1, (200, 200)).astype(np.float32)
    T[:, 60:75] -= 1.2           # 细长条:真形状 elong≈14 -> 渗漏
    T[80:120, 178:200] -= 1.2    # 贴边块:真形状 22×40 elong≈1.9 -> 非渗漏
    return T


def test_border_shape_measured_on_uncut_component():
    """边界带是"检测口径",不是"形状口径":形状须回查完整连通域。

    两个方向都要验:
      1. 贯穿全高的细长条(上下都跑出画面)保留全高,按真实形状判渗漏——
         若用被切过的掩膜,它会被切短、形状不可信;
      2. 右侧贴边块若按被切过的掩膜只剩 7px 宽的细条(rect≈1、elong≈5.7)
         就会被误判渗漏;用完整连通域量到 22×40(elong≈1.9)则不判。
    """
    from thermal_inspect import seepage_guard
    from thermal_inspect.seepage_guard import SeepageGuardParams
    seepage_guard.set_params(SeepageGuardParams(enabled=False))   # 本用例测边界带口径,
    p = Params()                                                  # 摆的是理想矩形冷条,
    p.detect.border_ignore_px = 15                                # 会把渗漏保护误当主题
    _, defects = run_single(_scene_border_shape(), p)

    strip = [d for d in defects if d.bbox[0] == 60 and d.bbox[2] == 15]
    assert strip, "贯穿全高的冷条应被检出"
    s = strip[0]
    assert s.bbox[3] == 200, \
        "细长条应按完整连通域报出全高(被切过的掩膜会只剩中间一段): %s" % (s.bbox,)
    assert s.label == "seepage", \
        "贯穿全高的细长条应判渗漏,实际 %s rect=%.2f elong=%.2f" \
        % (s.label, s.features["rect"], s.features["elong"])

    edge = [d for d in defects if d.bbox[0] >= 178]
    assert edge, "右侧贴边冷块应被检出"
    e = edge[0]
    assert e.bbox == (178, 80, 22, 40), \
        "贴边块应按完整连通域报出(被切过的掩膜只剩 7px 宽): %s" % (e.bbox,)
    assert e.label != "seepage", \
        "贴边块的真实形状不细长,不应判渗漏: rect=%.2f elong=%.2f" \
        % (e.features["rect"], e.features["elong"])


def _defect_sig(defects):
    """斑块的可比较签名(标签/符号/位置/面积),用于断言两次跑结果一致。"""
    return [(d.sign, d.label, d.bbox, d.area_px) for d in defects]
    seepage_guard.set_params(None)


def test_rect_mask_disabled_is_noop_enabled_is_not(tmp_path):
    """绝对矩形掩膜默认关闭时必须是**逐字节无操作**;启用时确实改变结果。

    两个方向都要断言,否则用例是空转(只测"关闭时没变"的话,一个从不生效的
    功能也能通过)。注意 summary.json 不能断言逐字节——它内嵌 params 快照,
    多出 rect_mask 段是预期的。
    """
    scene = _scene_with_window()

    ref = Params()
    T_ref, d_ref = run_single(scene, ref)

    off = Params()
    off.rect_mask.enabled = 0
    T_off, d_off = run_single(scene, off)
    assert np.array_equal(T_off, T_ref), "关闭时温度矩阵必须逐像素一致"
    assert _defect_sig(d_off) == _defect_sig(d_ref), "关闭时缺陷列表必须一致"

    on = Params()
    on.rect_mask.enabled = 1
    on.rect_mask.dt_c = 0.5        # 该合成场景的窗口温差
    debug = {}
    T_on, d_on = run_single(scene, on, debug=debug)
    assert not np.array_equal(T_on, T_ref), "启用时应确实改变温度矩阵(否则功能没生效)"
    assert "rects" in debug, "启用时应经 debug 出参回传矩形清单"

    # 关闭时 summary.json 除 params 外一致
    a = save_results(tmp_path, "off", T_off, d_off, off, scheme="single")
    b = save_results(tmp_path, "ref", T_ref, d_ref, ref, scheme="single")
    sa = json.loads((a / "summary.json").read_text(encoding="utf-8"))
    sb = json.loads((b / "summary.json").read_text(encoding="utf-8"))
    for k in ("params", "input"):   # params 多出 rect_mask 段;input 是输出目录名
        sa.pop(k), sb.pop(k)
    assert sa == sb, "关闭 rect_mask 时 summary(除 params/input 外)应与基准一致"


def test_rect_mask_stale_artifact_removed(tmp_path):
    """未启用时要删掉上一轮遗留的 rect_mask.png,否则会误判本次也跑了。"""
    T, defects = run_single(_scene_with_window(), Params())
    p = Params()
    p.rect_mask.enabled = 1
    p.rect_mask.dt_c = 0.5
    dbg = {}
    T2, d2 = run_single(_scene_with_window(), p, debug=dbg)
    a = save_results(tmp_path, "on", T2, d2, p, scheme="single", debug=dbg)
    assert (a / "rect_mask.png").exists(), "启用时应写调试图"

    b = save_results(tmp_path, "off", T, defects, Params(), scheme="single", debug={})
    assert not (b / "rect_mask.png").exists(), "未启用时不应留下 rect_mask.png"


def test_border_band_oversize_falls_back():
    """边界带覆盖全图时回退为不过滤并告警,不返回空结果。"""
    T, _ = run_single(np.full((64, 64), 25.0, np.float32), Params())
    assert np.all(T == T.flat[0])          # 平坦帧:校正后仍平坦
    p = Params()
    p.detect.border_ignore_px = 40         # 64/2 = 32 < 40 → 无内部像素
    _, defects = run_single(np.full((64, 64), 25.0, np.float32), p)
    assert defects == []                   # 不崩,平坦帧本就没有缺陷
