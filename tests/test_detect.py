"""检测模块测试:去趋势 / MAD / 阈值 / 连通域(对应 总体方案.md §2)。"""
import numpy as np

from thermal_inspect import detect


def test_detrend_extracts_local_anomaly():
    """远小于 σ 的局部热块应完整保留在异常图中,远处背景接近零。"""
    T = np.full((100, 100), 25.0, dtype=np.float32)
    T[48:52, 48:52] = 30.0  # 4×4 小块 << σ=20
    anom = detect.detrend(T, sigma=20.0)
    assert anom[50, 50] > 1.0
    assert abs(anom[5, 5]) < 0.5


def test_mad_sigma_robust():
    """MAD 不受极端值影响:含离群点时的估计仍为 1×1.4826。"""
    x = np.array([0.0, 1.0, 2.0, 3.0, 100.0], dtype=np.float32)
    # 中位数=2,|x−中位数| 的中位数=1
    assert abs(detect.mad_sigma(x) - 1.4826) < 1e-4


def test_threshold_and_blob_filtering():
    """噪声背景上的 6×6 热块被检出,且斑块边界与热块一致。"""
    rng = np.random.default_rng(1)
    T = rng.normal(25.0, 0.1, (100, 100)).astype(np.float32)
    T[10:16, 10:16] = 30.0
    anom = detect.detrend(T, sigma=5.0)
    z = detect.zscore(anom)
    masks = detect.threshold_z(z, 2.5)
    assert masks["warm"][13, 13]
    blobs = detect.extract_blobs(masks["warm"], min_area=25)
    assert len(blobs) == 1
    assert blobs[0]["area"] == 36
    assert blobs[0]["bbox"] == (10, 10, 6, 6)


def test_zscore_uses_given_sigma():
    """给定 σ 时 z = x / σ。"""
    x = np.array([1.0, 2.0], dtype=np.float32)
    z = detect.zscore(x, sigma=1.0)
    assert np.allclose(z, x)


def test_zscore_flat_returns_zeros():
    """平坦图像噪声估计为 0 → z 置全零(不做异常判定),不再用 1e-6 兜底
    (1e-6 会把阈值塌缩到 2.5e-6,全图误报)。"""
    x = np.full((10, 10), 5.0, dtype=np.float32)
    assert np.all(detect.zscore(x) == 0)
    assert np.all(detect.zscore(x, sigma=0.0) == 0)


def test_extract_blobs_mask_full_frame():
    """extract_blobs 的掩膜保持全帧尺寸(bbox 切片构建后粘贴回全帧)。"""
    mask = np.zeros((50, 50), dtype=bool)
    mask[10:16, 10:16] = True
    blobs = detect.extract_blobs(mask, min_area=1)
    assert len(blobs) == 1
    assert blobs[0]["mask"].shape == (50, 50)
    assert int(blobs[0]["mask"].sum()) == 36
    assert blobs[0]["bbox"] == (10, 10, 6, 6)


# ---------------------------------------------------------------- 边界带

def test_interior_mask_zero_keeps_all():
    """border_px=0:全图保留(旧行为)。"""
    keep = detect.interior_mask((20, 30), 0)
    assert keep.shape == (20, 30) and keep.all()


def test_interior_mask_cuts_all_four_sides():
    """四边各扣 border_px 行/列,内部保留。"""
    keep = detect.interior_mask((100, 200), 10)
    assert not keep[:10, :].any() and not keep[-10:, :].any()
    assert not keep[:, :10].any() and not keep[:, -10:].any()
    assert keep[10:-10, 10:-10].all()
    assert int(keep.sum()) == (100 - 20) * (200 - 20)


def test_interior_mask_oversize_returns_all_false():
    """band 覆盖全图时返回全 False,由调用方兜底(不在这里报错)。"""
    assert not detect.interior_mask((40, 40), 20).any()
    assert not detect.interior_mask((40, 40), 99).any()


