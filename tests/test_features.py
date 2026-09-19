"""特征提取测试(对应 总体方案.md §4 五个特征)。"""
import cv2
import numpy as np

from thermal_inspect.features import extract_features


def test_features_of_uniform_square():
    """均匀方形热块:ΔT≈温差、内部均匀度≈0、矩形度≈1、伸长率≈1。"""
    T = np.full((100, 100), 25.0, dtype=np.float32)
    blob = np.zeros((100, 100), dtype=bool)
    blob[40:60, 40:60] = True
    T[blob] = 30.0
    f = extract_features(blob, T, ring_kernel=5)
    assert abs(f["dT"] - 5.0) < 0.3
    assert f["uniform"] < 0.05
    assert f["rect"] > 0.9
    assert f["elong"] < 1.2


def test_verticality_of_stripes():
    """竖直细条 verticality≈1,水平细条 verticality≈0,伸长率>5。"""
    T = np.full((100, 100), 25.0, dtype=np.float32)
    v = np.zeros((100, 100), dtype=bool)
    v[30:70, 48:52] = True
    h = np.zeros((100, 100), dtype=bool)
    h[48:52, 30:70] = True
    fv = extract_features(v, T)
    fh = extract_features(h, T)
    assert fv["verticality"] > 0.95
    assert fh["verticality"] < 0.1
    assert fv["elong"] > 5.0
    assert fh["elong"] > 5.0


def test_empty_blob_raises():
    T = np.zeros((10, 10), dtype=np.float32)
    try:
        extract_features(np.zeros((10, 10), dtype=bool), T)
    except ValueError:
        return
    raise AssertionError("空斑块应抛出 ValueError")


def _rotated_rect(size=(120, 120), center=(60, 60), half=(20, 10), angle_deg=45.0):
    """画一个旋转矩形的斑块掩膜(全 True,用于验证最小外接矩形口径)。"""
    blob = np.zeros(size, dtype=bool)
    pts = cv2.boxPoints(((float(center[0]), float(center[1])),
                         (half[0] * 2, half[1] * 2), angle_deg)).astype(np.int32)
    cv2.fillPoly(blob, [pts], 1)
    return blob > 0


def test_rect_uses_min_area_rect():
    """矩形度按最小外接矩形面积:45° 斜矩形 rect 仍≈1(轴对齐口径约 0.5)。"""
    T = np.full((120, 120), 25.0, dtype=np.float32)
    blob = _rotated_rect()
    f = extract_features(blob, T)
    assert f["rect"] > 0.9, "斜矩形的最小外接矩形度应≈1,实际 %s" % f["rect"]


def test_elong_clamped_not_huge():
    """1px 宽竖条:伸长率 = 长边/1(退化钳制),不再出现 1e7 量级。"""
    T = np.full((40, 40), 25.0, dtype=np.float32)
    blob = np.zeros((40, 40), dtype=bool)
    blob[10:30, 20:21] = True  # 20px 高、1px 宽
    f = extract_features(blob, T)
    assert 15.0 <= f["elong"] <= 25.0, "elong 应为 长边/1px 的量级,实际 %s" % f["elong"]


def test_sharp_is_ring_band():
    """边界锐度度量斑块边界环带:平顶斑块的全部 |拉普拉斯| 能量在边界上,
    环带均值应显著高于全图均值(旧口径取斑块内部均值 ≈0,必不通过)。"""
    T = np.full((100, 100), 25.0, dtype=np.float32)
    blob = np.zeros((100, 100), dtype=bool)
    blob[40:60, 40:60] = True
    T[blob] = 30.0
    f = extract_features(blob, T, ring_kernel=5)
    assert f["sharp"] > f["sharp_ref"]


def test_bbox_and_lap_map_match_default():
    """bbox+lap_map 优化路径与默认全图路径的特征严格一致。"""
    rng = np.random.default_rng(0)
    T = rng.normal(25.0, 1.0, (100, 100)).astype(np.float32)
    blob = np.zeros((100, 100), dtype=bool)
    blob[30:60, 40:70] = True
    T[blob] += 3.0
    bbox = (40, 30, 30, 30)
    lap = np.abs(cv2.Laplacian(T, cv2.CV_32F))
    f0 = extract_features(blob, T, ring_kernel=5)
    f1 = extract_features(blob, T, ring_kernel=5, lap_map=lap,
                          sharp_ref=float(lap.mean()), bbox=bbox)
    for key in ("dT", "sharp", "uniform", "rect", "elong", "verticality"):
        assert np.allclose(f0[key], f1[key], atol=1e-5), "%s 不一致: %s vs %s" % (key, f0[key], f1[key])
    assert abs(f0["sharp_ref"] - f1["sharp_ref"]) < 1e-6
