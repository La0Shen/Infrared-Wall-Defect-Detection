"""分类规则测试(对应 总体方案.md §4 四条判定规则)。"""
from thermal_inspect.classify import classify
from thermal_inspect.config import ClassifyParams

BASE = dict(dT=0.0, sharp=1.0, sharp_ref=1.0, uniform=0.5,
            rect=0.5, elong=1.2, verticality=0.3, angle_deg=0.0)


def feat(**kw):
    d = dict(BASE)
    d.update(kw)
    return d


def test_window_rule():
    """窗户:冷斑 + 矩形度高 + 明显偏冷。"""
    cp = ClassifyParams()
    assert classify(feat(dT=-7.0, rect=0.95), "cold", cp) == "window"
    # ΔT 不够冷 → 不是窗户
    assert classify(feat(dT=-3.0, rect=0.95), "cold", cp) == "reject"
    # 热斑不能被判为窗户(z 符号与 ΔT 符号可能不一致,热斑被剔除=漏检)
    assert classify(feat(dT=-7.0, rect=0.95), "warm", cp) == "reject"


def test_hollow_rule():
    """空鼓:偏热 + 形状不规则;冷斑不能判为空鼓。"""
    cp = ClassifyParams()
    assert classify(feat(dT=2.5, rect=0.6), "warm", cp) == "hollow"
    assert classify(feat(dT=2.5, rect=0.6), "cold", cp) == "reject"
    # 矩形度过高(形状规则)→ 不是空鼓
    assert classify(feat(dT=2.5, rect=0.95), "warm", cp) == "reject"


def test_seepage_rule():
    """渗水:偏冷 + 细长。"""
    cp = ClassifyParams()
    assert classify(feat(dT=-2.5, elong=3.0, verticality=0.98), "cold", cp) == "seepage"
    assert classify(feat(dT=-0.5, elong=3.0, verticality=0.98), "cold", cp) == "reject"


def test_optional_vertical_rule():
    """开启"长轴偏垂直"后:竖直条通过,水平条拒绝。"""
    cp = ClassifyParams(seepage_require_vertical=True, seepage_angle_tol_deg=20)
    assert classify(feat(dT=-2.5, elong=3.0, verticality=0.98), "cold", cp) == "seepage"
    assert classify(feat(dT=-2.5, elong=3.0, verticality=0.2), "cold", cp) == "reject"


def test_optional_sharp_rules():
    """开启定性条件后:窗户需边界锐利,空鼓需边界弥散。"""
    cp = ClassifyParams(window_require_sharp=True, hollow_require_diffuse=True)
    assert classify(feat(dT=-7.0, rect=0.95, sharp=5.0, sharp_ref=1.0), "cold", cp) == "window"
    assert classify(feat(dT=-7.0, rect=0.95, sharp=0.2, sharp_ref=1.0), "cold", cp) == "reject"
    assert classify(feat(dT=2.5, rect=0.6, sharp=0.2, sharp_ref=1.0), "warm", cp) == "hollow"
    assert classify(feat(dT=2.5, rect=0.6, sharp=5.0, sharp_ref=1.0), "warm", cp) == "reject"


# ---------------------------------------------------------------- 形状渗漏规则

def test_shape_seepage_without_dt():
    """矩形度高 + 细长的冷斑块,不看 ΔT 也判渗漏(新规则的核心)。"""
    cp = ClassifyParams()
    # ΔT≈0,过不了 seepage_dt_c(-1.5),但形状确定 → 渗漏
    assert classify(feat(dT=0.0, rect=0.90, elong=3.0), "cold", cp) == "seepage"
    # 矩形度不够 → 不判
    assert classify(feat(dT=0.0, rect=0.60, elong=3.0), "cold", cp) == "reject"
    # 不够细长 → 不判
    assert classify(feat(dT=0.0, rect=0.90, elong=1.5), "cold", cp) == "reject"


def test_shape_seepage_only_for_cold():
    """热斑不适用形状渗漏规则(渗水是冷斑)。"""
    cp = ClassifyParams()
    assert classify(feat(dT=0.0, rect=0.90, elong=3.0), "warm", cp) == "reject"


def test_shape_seepage_ignores_dt_but_needs_both_shape_conditions():
    """两条形状条件是与关系,缺一不可;ΔT 完全不影响。"""
    cp = ClassifyParams()
    assert classify(feat(dT=5.0, rect=0.95, elong=4.0), "cold", cp) == "seepage"
    assert classify(feat(dT=5.0, rect=0.95, elong=1.2), "cold", cp) == "reject"
    assert classify(feat(dT=5.0, rect=0.40, elong=9.0), "cold", cp) == "reject"


def test_shape_seepage_optional_cold_floor():
    """seepage_shape_require_cold 默认关闭;开启后 ΔT 下限生效。"""
    f = feat(dT=-0.3, rect=0.90, elong=3.0)
    assert classify(f, "cold", ClassifyParams()) == "seepage"      # 默认不查 ΔT
    cp = ClassifyParams(seepage_shape_require_cold=True, seepage_shape_dt_c=-0.8)
    assert classify(f, "cold", cp) == "reject"                     # −0.3 不够冷
    assert classify(feat(dT=-1.2, rect=0.90, elong=3.0), "cold", cp) == "seepage"


def test_vertical_flag_gates_both_seepage_arms():
    """"长轴偏垂直"开关必须同时管住形状规则与 ΔT 规则,否则被静默绕过。"""
    cp = ClassifyParams(seepage_require_vertical=True, seepage_angle_tol_deg=20)
    horiz = feat(dT=0.0, rect=0.90, elong=3.0, verticality=0.2)      # 近水平
    vert = feat(dT=0.0, rect=0.90, elong=3.0, verticality=0.98)      # 近竖直
    assert classify(horiz, "cold", cp) == "reject"    # 形状规则被竖直条件拦住
    assert classify(vert, "cold", cp) == "seepage"
    # ΔT 规则同款
    assert classify(feat(dT=-2.5, elong=3.0, verticality=0.2), "cold", cp) == "reject"
    assert classify(feat(dT=-2.5, elong=3.0, verticality=0.98), "cold", cp) == "seepage"
