"""渗漏保护(seepage_guard)测试:改判判据 + 参数开关 + 真实数据真值。

这条规则只做一件事:**边缘太直的"渗漏"改判为非缺陷**。它有三条必须守住的边界,
每条都有对应用例:

  1. 边缘毛糙的真渗漏**不能**被改判(那等于把缺陷藏起来)——真实数据另有真值用例;
  2. **细线也要判**:实测细长冷线就是窗户隔板/横向接缝(人造构造),不是渗水
     (默认 min_short_px=0;曾经为"保护 test01 的 2px 真渗水"设成 5,那条被用户
     更正为窗户隔板后作废);
  3. 开关关掉就什么都不做——本模块的开关、以及 classify 两条渗水规则的开关都是。
"""
from pathlib import Path

import numpy as np
import pytest

from thermal_inspect import seepage_guard, window_guard
from thermal_inspect.config import Params
from thermal_inspect.pipeline import run_single
from thermal_inspect.seepage_guard import SeepageGuardParams

ROOT = Path(__file__).resolve().parents[1]


def _strip(short: int, long_: int, ragged: bool):
    """一条竖向冷条掩膜:ragged=True 时两侧交错挖缺口(毛边)。"""
    m = np.zeros((long_ + 40, short + 40), dtype=bool)
    m[20:20 + long_, 20:20 + short] = True
    if ragged:
        for i, r0 in enumerate(range(20, 20 + long_, 8)):
            if i % 2:
                m[r0:r0 + 8, 20:24] = False
            else:
                m[r0:r0 + 8, 20 + short - 4:20 + short] = False
    return m


@pytest.fixture(autouse=True)
def _reset_params_cache():
    """前后都清缓存:覆盖过的参数是进程级的,会污染其它测试文件。"""
    seepage_guard.set_params(None)
    yield
    seepage_guard.set_params(None)


# ---------------------------------------------------------------- 改判判据

def test_straight_elongated_seepage_becomes_reject():
    """人造直边的细长"渗漏"→ 改判非缺陷(test04 窗间墙柱那类)。"""
    v = seepage_guard.reconsider("seepage", _strip(16, 140, ragged=False),
                                 SeepageGuardParams())
    assert v.changed and v.label == "reject"
    assert v.regularity >= 0.5 and v.short_px > 5
    assert "人造直边物" in v.reason


def test_ragged_elongated_seepage_is_kept():
    """边缘毛糙的细长渗漏 → 维持原判(不能把真缺陷藏起来)。"""
    v = seepage_guard.reconsider("seepage", _strip(16, 140, ragged=True),
                                 SeepageGuardParams())
    assert not v.changed and v.label == "seepage"
    assert v.regularity < 0.5, "毛边应量出低规整度(实测 %.3f)" % v.regularity


def test_thin_line_is_judged_too():
    """细线照样判(默认 min_short_px=0):实测细长冷线就是窗户隔板/横向接缝。

    这条曾经反过来写(默认 5.0,细线一律不碰)——依据是"test01 那条 2px 线是真渗水",
    **用户后来更正它是窗户的隔板**,前提没了,默认随之改成 0。
    """
    for short in (2, 3, 4):
        v = seepage_guard.reconsider("seepage", _strip(short, 120, ragged=False),
                                     SeepageGuardParams())
        assert v.changed and v.label == "reject",             "短边 %dpx 的直边冷线应改判(窗户隔板那类)" % short


def test_min_short_px_is_the_knob():
    """门槛抬起来时,细线才会被放过(现场若发现某类细线该留,可以这么用)。"""
    gp = SeepageGuardParams(min_short_px=5.0)
    v = seepage_guard.reconsider("seepage", _strip(3, 120, ragged=False), gp)
    assert not v.changed and v.label == "seepage"
    assert "细线不判" in v.reason


def test_disabled_does_nothing():
    """开关关掉 → 原样返回,连量都不量。"""
    v = seepage_guard.reconsider("seepage", _strip(16, 140, ragged=False),
                                 SeepageGuardParams(enabled=False))
    assert not v.changed and v.label == "seepage" and v.reason == "渗漏保护已关闭"


def test_other_labels_untouched():
    """只动 seepage:窗户/空鼓/兜底一律不碰。"""
    m = _strip(16, 140, ragged=False)
    for label in ("window", "hollow", "reject"):
        v = seepage_guard.reconsider(label, m, SeepageGuardParams())
        assert v.label == label and not v.changed


def test_short_side_matches_elongation_convention():
    """短边与 window_guard.elongation 同口径(同一个最小外接矩形)。"""
    m = _strip(16, 140, ragged=False)
    el = window_guard.elongation(m)
    short = seepage_guard.short_side(m)
    assert abs(el * short - 140.0) < 2.0, "elong × 短边 ≈ 长边(实测 %.1f)" % (el * short)


# ---------------------------------------------------------------- 与管线串联

def _scene_with_straight_seepage():
    """合成场景:一条理想矩形的细长冷条(摆不出毛边,但足够验接线)。"""
    rng = np.random.default_rng(43)
    T = rng.normal(25.0, 0.1, (200, 200)).astype(np.float32)
    T[40:180, 95:107] = 22.0                       # 12×140 理想矩形冷条
    return T


def test_pipeline_relabels_straight_seepage():
    """经管线:理想矩形冷条被改判非缺陷,控制台留一行 [info]。"""
    _, defects = run_single(_scene_with_straight_seepage(), Params())
    assert "seepage" not in [d.label for d in defects], "直边冷条不该再报渗漏"
    assert [d for d in defects if d.label == "reject"], "应改判为兜底未分类"


def test_pipeline_keeps_ragged_seepage():
    """经管线:毛边冷条仍是渗漏(与上一条只差边界毛不毛)。"""
    T = _scene_with_straight_seepage().copy()
    for i, r0 in enumerate(range(40, 180, 8)):     # 把同一条冷条改成锯齿边
        if i % 2:
            T[r0:r0 + 8, 95:99] = 25.0
        else:
            T[r0:r0 + 8, 103:107] = 25.0
    _, defects = run_single(T, Params())
    assert "seepage" in [d.label for d in defects], "毛边冷条应仍是渗漏"


def test_pipeline_switch_off_restores_old_labels():
    """开关关掉 → 与加规则之前一致(两个方向都断言,否则用例是空转)。"""
    T = _scene_with_straight_seepage()
    seepage_guard.set_params(SeepageGuardParams(enabled=False))
    _, off = run_single(T, Params())
    assert "seepage" in [d.label for d in off]
    seepage_guard.set_params(SeepageGuardParams())
    _, on = run_single(T, Params())
    assert "seepage" not in [d.label for d in on]


# ---------------------------------------------------------------- 参数装载

def test_params_from_defaults_yaml_parses_with_right_types():
    """defaults.yaml 的 seepage_guard 段必须能通过严格校验;不冻结取值(现场会调)。"""
    p = seepage_guard.from_yaml(ROOT / "config" / "defaults.yaml")
    assert isinstance(p, SeepageGuardParams)
    assert isinstance(p.enabled, bool)
    for name in ("regular_min", "min_short_px", "edge_dev_ref_px", "edge_tol_px"):
        assert isinstance(getattr(p, name), float), name


def test_edge_knobs_match_window_guard_defaults():
    """边缘口径与 window_guard 是**同一套**:两处默认值不一致就会漂,这里钉住。"""
    from thermal_inspect.window_guard import WindowGuardParams
    a, b = SeepageGuardParams(), WindowGuardParams()
    assert a.edge_dev_ref_px == b.edge_dev_ref_px
    assert a.edge_tol_px == b.edge_tol_px


def test_unknown_key_and_bad_switch_raise(tmp_path):
    """键名写错 / 开关写成 "ture" 都要报错,不静默回退。"""
    f = tmp_path / "c.yaml"
    f.write_text("seepage_guard:\n  regular_mim: 0.5\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        seepage_guard.from_yaml(f)
    assert "regular_mim" in str(e.value)

    f2 = tmp_path / "d.yaml"
    f2.write_text("seepage_guard:\n  enabled: ture\n", encoding="utf-8")
    with pytest.raises(ValueError) as e2:
        seepage_guard.from_yaml(f2)
    assert "enabled" in str(e2.value)

    f3 = tmp_path / "e.yaml"
    f3.write_text("seepage_guard:\n  enabled: 0\n", encoding="utf-8")
    assert seepage_guard.from_yaml(f3).enabled is False    # YAML 常见写法也认


# ---------------------------------------------------------------- 真实帧真值(数据不入库)

_REAL = ROOT / "data" / "raw"
_skip = pytest.mark.skipif(not (_REAL / "test04.JPG").exists(),
                           reason="真实帧不在(data/raw 不入库)")


@_skip
def test_real_test04_fabric_false_positives_are_filtered():
    """test04 真值(用户给的):12 个"渗漏"里只有最右侧一条是真的。

    实测:6 根窗间墙柱(规整度 0.71~1.00)与 4 条 3~5px 横向接缝都应被改判;
    最右侧 (380,274,10,30)(规整度 0.30)必须是渗漏。
    另有一条是 ΔT 规则判的毛糙冷斑 (178,243,93,29),本模块管不了,仍会留着。
    """
    p = Params.from_yaml(ROOT / "config" / "defaults.yaml")
    from thermal_inspect.io import read_temperature
    _, defects = run_single(read_temperature(_REAL / "test04.JPG"), p)
    seep = [d for d in defects if d.label == "seepage"]
    for x, y, w, h in ((258, 53, 14, 109), (65, 55, 18, 105), (159, 54, 18, 107),
                       (62, 271, 20, 132), (157, 272, 18, 131), (255, 273, 15, 130)):
        assert not [d for d in seep if d.bbox[0] == x and d.bbox[1] == y], \
            "窗间墙柱 (%d,%d) 不该再报渗漏" % (x, y)
    assert [d for d in seep if d.bbox[0] == 380 and d.bbox[1] == 274], \
        "最右侧那条真渗漏必须留着"


@_skip
def test_real_test01_window_partition_is_filtered():
    """test01 真值(用户更正):那条 2px 水平线是**窗户的隔板**,是假渗水。

    项目笔记原来写着"唯一的真渗水是水平的"指的就是它——用户后来推翻了这个说法,
    本模块的默认值(细线也判)也据此改过。它现在应当被判成非缺陷。
    """
    p = Params.from_yaml(ROOT / "config" / "defaults.yaml")
    from thermal_inspect.io import read_temperature
    _, defects = run_single(read_temperature(_REAL / "test01.JPG"), p)
    assert not [d for d in defects if d.label == "seepage"
                and d.bbox[0] == 306 and d.bbox[1] == 120], "窗户隔板不该再报渗漏"


@_skip
def test_real_test02_strip_still_seepage():
    """test02:左柱(真渗漏,由窗户保护释放出来)不能被渗漏保护再改判掉。"""
    p = Params.from_yaml(ROOT / "config" / "defaults.yaml")
    from thermal_inspect.io import read_temperature
    _, defects = run_single(read_temperature(_REAL / "test02.JPG"), p)
    assert [d for d in defects if d.label == "seepage" and d.bbox[2] < 60 and d.bbox[3] > 300]


# ---------------------------------------------------------------- 两条渗水鉴定规则的开关

def _scene_shape_rule_only():
    """只有形状规则会判的一条细长冷条:rect≈1、elong>2,但 dT 很弱(ΔT 规则不成立)。"""
    rng = np.random.default_rng(5)
    T = rng.normal(25.0, 0.1, (240, 240)).astype(np.float32)
    T[20:220, 110:140] = 24.3          # 比背景只冷 0.7℃:feature dT 过不了 seepage_dt_c
    return T


def _scene_dt_rule_only():
    """只有 ΔT 规则会判的一条毛糙冷斑:够冷(dT≈-3)但 rect 低(形状规则要求 >0.80)。"""
    rng = np.random.default_rng(6)
    T = rng.normal(25.0, 0.1, (240, 240)).astype(np.float32)
    T[20:220, 110:140] = 22.0          # 冷条主体
    for i, r0 in enumerate(range(20, 220, 8)):   # 两侧挖深缺口 → rect 掉到 0.8 以下
        if i % 2:
            T[r0:r0 + 8, 110:121] = 25.0
        else:
            T[r0:r0 + 8, 129:140] = 25.0
    return T


def test_shape_rule_switch_off_kills_shape_seepage():
    """关掉形状规则 → 它判出的渗漏消失(两个方向都断言)。

    这里同时把本模块自己的改判关掉(`enabled=False`):场景摆的是一条**理想矩形**
    冷条,本模块会先把它改判掉,那样就看不到形状规则的输出了。两个开关是彼此独立的
    —— 一个管"规则判不判",一个管"判出来的要不要改判"。
    """
    T = _scene_shape_rule_only()
    seepage_guard.set_params(SeepageGuardParams(enabled=False))
    _, on = run_single(T, Params())
    assert "seepage" in [d.label for d in on], "开着时应由形状规则判出渗漏"
    seepage_guard.set_params(SeepageGuardParams(enabled=False, shape_rule_on=False))
    _, off = run_single(T, Params())
    assert "seepage" not in [d.label for d in off], "关掉后不该再有渗漏"


def test_dt_rule_switch_off_kills_dt_seepage():
    """关掉 ΔT 规则 → 它判出的渗漏消失,而形状规则那条不受影响。"""
    T = _scene_dt_rule_only()
    _, on = run_single(T, Params())
    assert "seepage" in [d.label for d in on]
    seepage_guard.set_params(SeepageGuardParams(dt_rule_on=False))
    _, off = run_single(T, Params())
    assert "seepage" not in [d.label for d in off]


def test_rule_switches_do_not_mutate_caller_params():
    """开关走副本:调用方那份 Params 的阈值一个字不能改(否则参数快照会失真)。"""
    from thermal_inspect.config import ClassifyParams
    cp = ClassifyParams()
    before = (cp.seepage_rect, cp.seepage_dt_c)
    seepage_guard.set_params(SeepageGuardParams(shape_rule_on=False, dt_rule_on=False))
    eff = seepage_guard.effective_classify_params(cp)
    assert eff is not cp, "关掉规则时给的是副本"
    assert (cp.seepage_rect, cp.seepage_dt_c) == before, "原对象必须原封不动"
    seepage_guard.set_params(SeepageGuardParams())
    assert seepage_guard.effective_classify_params(cp) is cp, "都开着时原样返回(零开销)"


def test_rule_switches_accept_01_and_reject_garbage(tmp_path):
    """两个新开关同样认 0/1,写错报错带键名。"""
    f = tmp_path / "s.yaml"
    f.write_text("seepage_guard:\n  shape_rule_on: 0\n  dt_rule_on: 1\n", encoding="utf-8")
    gp = seepage_guard.from_yaml(f)
    assert gp.shape_rule_on is False and gp.dt_rule_on is True
    f2 = tmp_path / "t.yaml"
    f2.write_text("seepage_guard:\n  shape_rule_on: ture\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        seepage_guard.from_yaml(f2)
    assert "shape_rule_on" in str(e.value)


# ---------------------------------------------------------------- 边缘口径两个子口径的开关

def _strip_with_bump(bump: int):
    """直边竖条 + 一侧一个鼓包:两个子口径会给出**不同**判决的那种形状。"""
    m = np.zeros((200, 60), dtype=bool)
    m[20:160, 20:36] = True
    if bump:
        m[70:110, 36:36 + bump] = True
    return m


def test_sub_criterion_switches_change_the_verdict():
    """拆开两个子口径后,单开一项确实能给出不同判决(否则开关是白加的)。

    实测这条带鼓包的形状:两项都算 → 规整度 0.000(维持渗漏);
    只算突出占比 → 0.500(改判)。两个口径看的是不同的东西,分开才有意义。
    """
    m = _strip_with_bump(6)
    both = seepage_guard.reconsider("seepage", m, SeepageGuardParams())
    assert not both.changed, "两项都算:鼓包把直线拟合拖垮了 → 维持渗漏"
    prot_only = seepage_guard.reconsider("seepage", m, SeepageGuardParams(line_on=False))
    assert prot_only.changed, "只算突出占比:鼓包只占一小段 → 改判"
    assert "只算突出占比" in prot_only.reason
    line_only = seepage_guard.reconsider("seepage", m, SeepageGuardParams(prot_on=False))
    assert not line_only.changed and "只算直线拟合" in line_only.reason


def test_both_sub_criteria_off_means_always_regular():
    """两项都关 = 恒判"规整"(全部改判)——踩坑口径,如实钉住。"""
    v = seepage_guard.reconsider("seepage", _strip_with_bump(6),
                                 SeepageGuardParams(line_on=False, prot_on=False))
    assert v.changed and v.label == "reject" and v.regularity == 1.0
    assert "两个子口径都关着" in v.reason


def test_sub_switches_accept_01_and_reject_garbage(tmp_path):
    """两个子口径开关同样认 0/1,写错报错带键名。"""
    f = tmp_path / "u.yaml"
    f.write_text("seepage_guard:\n  line_on: 0\n  prot_on: 1\n", encoding="utf-8")
    gp = seepage_guard.from_yaml(f)
    assert gp.line_on is False and gp.prot_on is True
    f2 = tmp_path / "v.yaml"
    f2.write_text("seepage_guard:\n  prot_on: ture\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        seepage_guard.from_yaml(f2)
    assert "prot_on" in str(e.value)
