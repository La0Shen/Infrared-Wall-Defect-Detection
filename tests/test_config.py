"""配置严格化测试:未知键/非法 null 报错,合法 null 字段正常。"""
import pytest

from thermal_inspect.config import Params, from_mapping


def test_unknown_key_raises_with_hint():
    """拼写错误的键必须报错并给出最近似键名,不得静默回退默认值。"""
    with pytest.raises(ValueError) as ei:
        from_mapping({"detect": {"z_threshhold": 2.0}})
    assert "z_threshhold" in str(ei.value)
    assert "z_threshold" in str(ei.value)


def test_none_for_nonnullable_raises():
    """不可空字段写 null 必须报错并指明键名,防止 None 直达 numpy。"""
    with pytest.raises(ValueError) as ei:
        from_mapping({"detect": {"z_threshold": None}})
    assert "z_threshold" in str(ei.value)
    assert "detect" in str(ei.value)


def test_nullable_none_ok():
    """Optional 字段写 null 正常。"""
    p = from_mapping({"preprocess": {"distance_m": None}})
    assert p.preprocess.distance_m is None


def test_defaults_yaml_loads():
    """默认配置文件必须能通过严格校验,且键的类型/取值域合法。

    **只断言契约,不冻结具体值。** 这条用例的历史教训:曾经写死
    `display.show_reject == 1` 和 `window_mask.enabled is True`,结果用户一调参
    (关掉窗户掩膜做 A/B、打开矩形掩膜)用例就变红,而配置本身完全合法——
    `defaults.yaml` 恰恰是"现场随手调"的落点。要钉"出厂默认",钉在代码默认上
    (见 test_rect_mask_default_disabled_and_wired 的 `Params()` 断言)。
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    p = Params.from_yaml(str(root / "config" / "defaults.yaml"))

    # 布尔开关:必须是 bool
    assert isinstance(p.window_mask.enabled, bool)
    for name in ("window_require_sharp", "hollow_require_diffuse",
                 "seepage_require_vertical"):
        assert isinstance(getattr(p.classify, name), bool)
    # 浮点阈值:必须是数值(不冻结具体取值)
    for v in (p.window_mask.z_threshold, p.window_mask.grow_tol_c,
              p.classify.window_rect, p.classify.hollow_dt_c,
              p.rect_mask.dt_c, p.rect_mask.approx_eps, p.rect_mask.min_edge_px):
        assert isinstance(v, float)
    # 整数/像素量:必须非负
    for v in (p.window_mask.grow_max_px, p.rect_mask.min_area_px,
              p.detect.border_ignore_px, p.features.ring_kernel):
        assert isinstance(v, int) and v >= 0
    # display 段:0/1 开关 + 非负长度下限
    for name in ("window", "hollow", "seepage", "reject"):
        assert getattr(p.display, "show_" + name) in (0, 1)
        assert getattr(p.display, "min_len_%s_px" % name) >= 0
    # 绝对矩形掩膜开关:0/1(默认关闭由上面那条用例钉在代码默认上)
    assert p.rect_mask.enabled in (0, 1)


# ---------------------------------------------------------------- display 段

def test_display_flag_must_be_0_or_1():
    """显示开关只收 0/1:2、-1、字符串"ture"、true、1.0 都必须报错。

    这些值 bool() 后都为真,_build 又无类型校验,不查就会静默画错。
    """
    for bad in (2, -1, "ture", True, False, 1.0, None):
        with pytest.raises(ValueError) as ei:
            from_mapping({"display": {"show_hollow": bad}})
        assert "show_hollow" in str(ei.value), bad
        assert "display" in str(ei.value), bad


def test_display_min_len_must_be_nonnegative_int():
    """长度下限只收非负整数。"""
    for bad in (-1, "30", 2.5, True):
        with pytest.raises(ValueError) as ei:
            from_mapping({"display": {"min_len_seepage_px": bad}})
        assert "min_len_seepage_px" in str(ei.value), bad


def test_display_partial_override_keeps_other_defaults():
    """只写一个键时,其余键回落到默认值(与其他段同口径)。"""
    p = from_mapping({"display": {"show_reject": 0}})
    assert p.display.show_reject == 0
    assert p.display.show_hollow == 1
    assert p.display.min_len_window_px == 0


def test_rect_mask_enabled_must_be_0_or_1():
    """绝对矩形掩膜开关只收 0/1(与 display.show_* 同口径)。"""
    for bad in (2, -1, "ture", True, False, 1.0, None):
        with pytest.raises(ValueError) as ei:
            from_mapping({"rect_mask": {"enabled": bad}})
        assert "enabled" in str(ei.value), bad
        assert "rect_mask" in str(ei.value), bad


def test_rect_mask_pixel_keys_must_be_nonneg_int():
    """像素类键(闭运算核/面积/膨胀/生长/修复半径)只收非负整数。"""
    for key in ("morph_close", "min_area_px", "dilate_px",
                "grow_max_px", "inpaint_radius"):
        with pytest.raises(ValueError) as ei:
            from_mapping({"rect_mask": {key: -1}})
        assert key in str(ei.value), key


def test_rect_mask_default_disabled_and_wired():
    """默认关闭;且 YAML 段确实接进了 from_mapping。

    接线断言不能省:若忘了在 from_mapping 里取 rect_mask,_build 永远不会被
    调用,配置能正常加载、enabled: 1 却毫无作用且不报错。
    """
    assert Params().rect_mask.enabled == 0
    assert from_mapping({"rect_mask": {"enabled": 1}}).rect_mask.enabled == 1
    # 未写该段时回落到代码默认
    assert from_mapping({}).rect_mask.enabled == 0


def test_border_ignore_px_must_be_nonneg_int():
    """边界带宽度只收非负整数(负数会静默等于不过滤,字符串会深层崩)。"""
    for bad in (-1, "15", 2.5, True):
        with pytest.raises(ValueError) as ei:
            from_mapping({"detect": {"border_ignore_px": bad}})
        assert "border_ignore_px" in str(ei.value), bad
        assert "detect" in str(ei.value), bad


def test_border_ignore_px_zero_allowed():
    """0 合法(表示不过滤,恢复旧行为)。"""
    assert from_mapping({"detect": {"border_ignore_px": 0}}) \
        .detect.border_ignore_px == 0


def test_display_unknown_key_suggests():
    """漏写 _px 后缀等拼写错误必须报错并给出最近似键名。"""
    with pytest.raises(ValueError) as ei:
        from_mapping({"display": {"min_len_reject": 30}})
    assert "min_len_reject_px" in str(ei.value)


def test_display_shows_semantics():
    """shows():开关 0 一律不画;长度用 max(w,h) 且含等号(>=)。"""
    from thermal_inspect.config import DisplayParams
    d = DisplayParams()
    assert d.shows("hollow", (0, 0, 4, 6)) is True       # 默认全画
    d.show_hollow = 0
    assert d.shows("hollow", (0, 0, 4, 6)) is False
    d = DisplayParams(min_len_hollow_px=6)
    assert d.shows("hollow", (0, 0, 4, 6)) is True       # 长边 == 阈值 → 画
    assert d.shows("hollow", (0, 0, 4, 5)) is False      # 长边 < 阈值 → 不画
    assert d.shows("hollow", (0, 0, 7, 2)) is True       # 取 max(w,h)
    assert d.shows("unknown", (0, 0, 1, 1)) is True      # 未知类别按显示处理
    # 开关与长度是与关系
    assert DisplayParams(show_reject=0, min_len_reject_px=0).shows(
        "reject", (0, 0, 99, 99)) is False
