"""方案一(单帧)主流程编排与结果输出。对应 总体方案.md §2、§4。"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import (classify, detect, features as feat_mod, preinpaint_overlay,
               preprocess, rect_mask, seepage_guard, window_guard)
from .config import DisplayParams, Params
from .io import read_temperature


@dataclass
class Defect:
    """一个检出的候选斑块。"""

    sign: str                          # 'warm' 热斑 / 'cold' 冷斑(取自温度图)
    label: str                         # window / hollow / seepage / reject
    area_px: int
    bbox: Tuple[int, int, int, int]    # (x, y, w, h)
    mask: np.ndarray                   # bool 掩膜(不写入 JSON)
    features: dict
    area_m2: Optional[float] = None    # 物理面积(GSD 已知时)
    source: str = "single"             # 单帧管线固定值(字段保留以兼容输出格式)
    component: Optional[int] = None    # 单帧管线不使用(惰性默认值,兼容输出格式)
    comp_kind: Optional[str] = None    # 单帧管线不使用(惰性默认值,兼容输出格式)


# ---------------------------------------------------------------- 方案一

def _rect_of(mask: np.ndarray) -> float:
    """最小外接矩形度 = 面积 / 最小外接矩形面积(与 extract_features 的 rect 同口径)。"""
    pts = np.argwhere(mask).astype(np.int32)
    try:
        _, (ma, mi), _ = cv2.minAreaRect(pts)
        return float(mask.sum() / max(float(ma) * float(mi), 1.0))
    except cv2.error:
        _, _, w, h = cv2.boundingRect(mask.astype(np.uint8))
        return float(mask.sum() / max(w * h, 1))


def _grow_mask_to_background(T: np.ndarray, mask: np.ndarray,
                             dilate_px: int, grow_tol_c: float,
                             grow_max_px: int) -> np.ndarray:
    """把窗户掩膜向外扩张,直到最外圈温度回到局部背景水平(覆盖过渡带)。

    掩膜按外接矩形填充只盖窗本体;去噪/窗框导热会在窗外留下一段渐变的
    过渡带,固定 dilate_px 盖不全 → 修复后残留一圈过渡环。做法:先做基础
    膨胀(dilate_px,盖窗框),再逐像素外扩;每步把新增环带温度与更外一圈
    参考带比较,环带回到"参考带 − grow_tol_c"以上即停(用 T 局部比较而非
    全局中位数:墙面整体有温度梯度,全局口径会在冷区过度扩张;也不可用 z
    ——去趋势在窗边产生正过冲,z 环带在过渡带外沿会提前"回零")。
    环带/参考带均取中位数比较:对数百像素的带稳健,暖斑与噪声离群像素
    不影响判据;矩形角部的过渡带比四边慢半拍到一拍,角部可能残留零点几
    度的冷缝——由第二遍检测的 exclude_overlap 排除兜底(见 run_single)。
    grow_max_px 兜底防无界扩张(0=关闭自适应生长,仅用 dilate_px)。
    """
    m = mask
    if dilate_px > 0:
        k = 2 * int(dilate_px) + 1
        m = cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    kernel = np.ones((3, 3), np.uint8)
    ref_kernel = np.ones((9, 9), np.uint8)          # 参考带:环带外 4px
    for _ in range(int(grow_max_px)):
        grown = cv2.dilate(m.astype(np.uint8), kernel) > 0
        ring = grown & ~m
        if not ring.any():                          # 已触到图像边界,无处可扩
            break
        ref = cv2.dilate(grown.astype(np.uint8), ref_kernel) > 0
        ref_band = ref & ~grown
        if not ref_band.any():                      # 参考带触到边界,不再扩
            break
        if float(np.median(T[ring])) >= float(np.median(T[ref_band])) - grow_tol_c:
            break                                   # 环带已回到局部背景水平
        m = grown
    return m


def _window_mask(T: np.ndarray, z: np.ndarray, params: Params,
                 lap=None, sharp_ref=None, g=None, sigma=None
                 ) -> Tuple[Optional[np.ndarray], List[Defect]]:
    """第一遍:从 z 冷侧找窗户区域,返回 (掩膜, 窗户缺陷列表)。

    窗户反光使窗内温度不均,窗户整体仅略冷于墙面(实测 0.5~1.7℃),
    检测层阈值抓不到 → 用更宽松的 z 阈值 + 形态学闭运算把打碎的区域
    合并成块;第二遍检测时与掩膜重叠的候选斑块直接排除(窗户区域不作为
    识别条件)。

    判定规则:
      - 块均值须比图像中位数冷(dT < dT_max_c),滤掉图像边缘的暖伪影;
      - 直接矩形路径:rect > rect_direct 且宽高比 ∈ [0.4, 3.5](如冷矩形窗);
      - 区域块路径:rect ≤ rect_direct 且宽高比 ∈ [aspect_min, aspect_max]
        (窗户群合并成的条带/块;渗水细长条 rect≈1 或宽高比 <0.12 不在此列,
        不会被误掩)。

    sigma:MAD 噪声 σ(℃),供 `window_guard` 的强边缘口径用;None 时内部现算
    (管线里由 run_single 传入,与 z 用的是同一个 σ)。

    返回的第二个列表名为 windows,但**不保证全是窗户**:被 `window_guard` 判为
    "极端狭长 + 内部均衡、不是窗户"的块,会以 `label="seepage"` 混在里面(它们与
    窗户一样"移出净墙",只是标签不同)。调用方按 label 处理即可。
    """
    wm = params.window_mask
    if not wm.enabled:
        return None, []
    if sigma is None:  # 非管线调用方(测试等)没传:用与 z 同口径的 MAD 噪声现算
        sigma = detect.mad_sigma(
            detect.detrend(T, params.detect.detrend_sigma_px), params.detect.mad_scale)
    med = float(np.median(T))
    cold = z < -wm.z_threshold
    mask = np.zeros(T.shape, dtype=bool)
    windows: List[Defect] = []
    # 两遍:第一遍小闭运算抓单窗矩形(直接路径);第二遍大闭运算合并成排/成列
    # 的窗户区域块(块路径,仅接受明显细长的块——近方形冷块多为去趋势伪影)
    for close, direct_only in ((wm.close_direct, True), (wm.close_kernel, False)):
        c = cold
        if close > 0:
            c = cv2.morphologyEx(cold.astype(np.uint8), cv2.MORPH_CLOSE,
                                 np.ones((close, close), np.uint8)) > 0
        for blob in detect.extract_blobs(c, min_area=wm.min_area_px):
            m = blob["mask"]
            x, y, w, h = blob["bbox"]
            if mask.any() and _masked_out(m, mask, wm.exclude_overlap):
                continue  # 已被上一遍覆盖
            dT = float(T[m].mean() - med)
            if not dT < wm.dT_max_c:
                continue
            rect = _rect_of(m)
            aspect = w / max(h, 1)
            if direct_only:
                is_window = rect > wm.rect_direct and 0.4 <= aspect <= 3.5
            else:
                is_window = (rect <= wm.rect_direct
                             and wm.aspect_min <= aspect <= wm.aspect_max
                             and (aspect < wm.block_aspect_lo or aspect > wm.block_aspect_hi))
            if not is_window:
                continue
            # 窗形渗漏保护(本项目新增,算法在 window_guard.py):块路径为了合并成排
            # 窗户而接受细长冷块,一条**连续均匀的细长冷带**也会落进来(实测 test02
            # 左柱 41×378、长宽比 9.4),被整块当成窗户掩掉、渗漏从清单里消失。这里
            # 多问一道:极端狭长且内部温度均衡 → 不是窗户。
            verdict = window_guard.judge(T, z, cold, m, sigma, bbox=blob["bbox"])
            if verdict.triggered and not verdict.is_window:
                # 按渗漏输出,但区域**照旧移出净墙**:与窗户同款 bbox 填充,否则第二遍
                # 检测会在同一块地方再报一堆重复候选(实测 test02 已有 85 个 reject)。
                # 特征/几何都取"主导原始冷块"(真实物体),不取闭运算合成的块。
                cm, cb = verdict.component, verdict.bbox
                mask[y:y + h, x:x + w] = True
                f = feat_mod.extract_features(cm, T, params.features.ring_kernel,
                                              lap_map=lap, sharp_ref=sharp_ref, bbox=cb)
                area_m2 = float(cm.sum()) * g ** 2 if g else None
                windows.append(Defect(sign="cold", label="seepage", area_px=int(cm.sum()),
                                      bbox=cb, mask=cm, features=f, area_m2=area_m2))
                print("[info] 窗形渗漏保护:块 (%d,%d,%d,%d) 非窗户 → 渗漏(%s)"
                      % (x, y, w, h, verdict.reason))
                continue
            # 掩膜按外接矩形填充(而非斑块本身):窗内反光暖区在冷掩膜里是孔洞,
            # 按斑块取并集盖不住;"整个窗户区域不作为识别条件"语义即整块矩形排除
            mask[y:y + h, x:x + w] = True
            f = feat_mod.extract_features(m, T, params.features.ring_kernel,
                                          lap_map=lap, sharp_ref=sharp_ref, bbox=blob["bbox"])
            area_m2 = float(blob["area"]) * g ** 2 if g else None
            windows.append(Defect(sign="cold", label="window", area_px=blob["area"],
                                  bbox=blob["bbox"], mask=m, features=f, area_m2=area_m2))
    if not mask.any():
        return None, []
    # 自适应生长:先膨胀盖窗框,再逐像素外扩到局部背景水平,
    # 把去噪/导热造成的过渡带一并纳入掩膜(修复后不留过渡环)
    mask = _grow_mask_to_background(T, mask, wm.dilate_px,
                                    wm.grow_tol_c, wm.grow_max_px)
    return mask, windows


def _masked_out(blob_mask: np.ndarray, win_mask: Optional[np.ndarray],
                overlap_thr: float) -> bool:
    """候选斑块与窗户掩膜的覆盖率是否超过阈值(超过即被排除)。"""
    if win_mask is None:
        return False
    area = int(blob_mask.sum())
    if area == 0:
        return False
    cov = float(np.logical_and(blob_mask, win_mask).sum()) / area
    return cov > overlap_thr


def _inpaint_windows(T: np.ndarray, win_mask: Optional[np.ndarray],
                     radius: int = 3) -> np.ndarray:
    """把窗户区域(掩膜已含过渡带)用局部背景修复替换,即"删掉窗户"。

    用 cv2.inpaint(NS,求解拉普拉斯方程、谐波延续背景)而非 Telea:掩膜边界
    必然落在过渡带的斜坡上,Telea 沿坡逐层传播时偶数/奇数像素解耦,填充区
    会出现 ±1℃ 的棋盘纹(实测 24.4/26.5 交替),下一段检测把它报成整片斑块;
    NS 的谐波解单调平滑,天然适合"按背景色填平"。也不用常数/中位数填充:
    那会在补丁边缘制造新的人工边缘,下一段检测会把它误判为新缺陷。
    掩膜的过渡带覆盖由 _window_mask 的 dilate_px + 自适应生长完成,此处只负责填充。
    """
    if win_mask is None or not win_mask.any():
        return T
    m = win_mask.astype(np.uint8) * 255
    return cv2.inpaint(T.astype(np.float32), m, float(radius), cv2.INPAINT_NS)


def run_single(T: np.ndarray, params: Params,
               debug: Optional[dict] = None) -> Tuple[np.ndarray, List[Defect]]:
    """方案一完整管线:输入温度矩阵(℃)→ (校正后的温度矩阵, 缺陷列表)(总体方案.md §2)。

    返回的 T 为发射率校正+去噪后的矩阵(与缺陷计算所用一致),供保存与
    追溯——保证 temperature.npy 是"校正后的温度矩阵"。

    窗户掩膜:先识别窗户区域(含过渡带),再用局部背景修复把窗户从温度图上
    "删除";后续检测在净墙上进行,窗户反光不再产生虚假候选。

    绝对矩形掩膜(`rect_mask.enabled`,**调试用**):按绝对温差转码 + 几何四边
    找**规则粗边矩形**,填平(掩埋)后沿用原方案继续检测。默认关闭。

    debug:可选字典。启用矩形掩膜时被填入 "rect_mask"(掩膜)与
    "rects"(矩形清单);**无论是否启用**,都填入 "T_preinpaint"(校正+去噪后、
    修复窗前的温度矩阵快照),供 save_results 写 overlay_preinpaint.png(见
    preinpaint_overlay.py)。None 时不做任何记录(与 read_temperature 的
    warnings 出参同一惯例),此时那张图不会产出——想要它就得传一个字典进来。
    """
    pp, dp, fp, cp, wm, rm = (params.preprocess, params.detect, params.features,
                              params.classify, params.window_mask, params.rect_mask)
    # 渗水鉴定两条规则的开关(见 seepage_guard.effective_classify_params):关掉的那条
    # 阈值被推到不可能达到 → 永不成立。都开着时返回的就是 cp 本身,零开销。
    cp_eff = seepage_guard.effective_classify_params(cp)

    # 共用预处理(总体方案.md §1.2):发射率校正 → 去噪
    T = preprocess.correct_emissivity(T, pp.emissivity, pp.reflected_temp_c)
    T = preprocess.denoise(T, pp.denoise_kernel)
    if debug is not None:
        # 修复前快照:底下所有修复(rect_mask 掩埋、窗户掩膜填充)都会就地改写 T,
        # 快照取在"校正+去噪之后、任何修复之前",正是"原本的热成像图"那个口径。
        # 拷贝一份:后面 T 被 _inpaint_windows 重新赋值,但若某段改成原地改写,
        # 引用同一块内存会让快照跟着变。
        debug["T_preinpaint"] = T.copy()

    # GSD:已知拍摄距离时换算物理面积
    g = preprocess.gsd(pp.distance_m, pp.gsd_divisor)

    # 边界带:照片最外 border_ignore_px px 视为墙,不参与检测(窗外未拍全、
    # 边界外无墙可比,会在边界产生大量伪影)。只作用于下方检测掩膜,不作用于
    # 窗户掩膜——窗户掩膜是"删除+修复"机制,在那里裁剪会把窗户残留留在边界带
    # 内(实测 temperature.npy 边界留下 4.1℃ 冷条,overlay 上可见接缝),且对
    # 那两个大窗区块毫无作用。T 随后被 _inpaint_windows 重新赋值但形状不变,
    # 故此处一次性构造的 keep 全程有效。
    keep = detect.interior_mask(T.shape, dp.border_ignore_px)
    if dp.border_ignore_px > 0 and not keep.any():
        print("[warn] border_ignore_px=%d 已覆盖全图(短边 %d),回退为不过滤"
              % (dp.border_ignore_px, min(T.shape)))
        keep = np.ones(T.shape, dtype=bool)

    # 绝对矩形掩膜(调试用,默认关闭,由 rect_mask.enabled 控制):转码找规则粗边
    # 矩形,把矩形区域用局部背景修复填平(掩埋),沿用原方案继续在净墙上检测。
    rect_rects: List[dict] = []
    if rm.enabled:
        rmask, rect_rects = rect_mask.detect_rectangles(T, rm)
        if rmask.any():
            rmask = cv2.dilate(rmask.astype(np.uint8),
                               np.ones((2 * rm.dilate_px + 1,) * 2, np.uint8)) > 0
            T = _inpaint_windows(T, rmask, rm.inpaint_radius)
            print("[info] 绝对矩形掩膜:掩埋 %d 个规则粗边矩形" % len(rect_rects))
            if debug is not None:
                debug["rect_mask"] = rmask
                debug["rects"] = rect_rects

    # 窗户检测 + 删除(仅 enabled 时):识别窗户区域并膨胀覆盖过渡带,
    # 再用局部背景修复把窗户从温度图上删掉;后续检测在净墙上进行
    window_defects: List[Defect] = []
    win_mask = None
    if wm.enabled:
        anom = detect.detrend(T, dp.detrend_sigma_px)
        sigma = detect.mad_sigma(anom, dp.mad_scale)
        z = detect.zscore(anom, sigma)
        lap = np.abs(cv2.Laplacian(T, cv2.CV_32F))
        win_mask, window_defects = _window_mask(T, z, params, lap=lap,
                                                sharp_ref=float(lap.mean()), g=g,
                                                sigma=sigma)
        T = _inpaint_windows(T, win_mask, wm.inpaint_radius)

    # 方案一(总体方案.md §2):去趋势 → MAD 噪声估计 → z 标准化 → 阈值 → 连通域
    anom = detect.detrend(T, dp.detrend_sigma_px)
    sigma = detect.mad_sigma(anom, dp.mad_scale)
    z = detect.zscore(anom, sigma)
    full = detect.threshold_z(z, dp.z_threshold)          # 未切:供形状回查
    masks = {k: (v & keep) for k, v in full.items()}      # 边界带=墙,不检测

    # 每个极性只标注一次完整连通域。边界带是"检测口径"而非"形状口径":
    # 掩膜被切过的斑块(如一条从画面上下两端跑出去的渗水),其外轮廓会沿边界
    # 被切直,rect/elong 被人为拉高(实测 rect 0.66→1.00、elong 1.91→6.00)。
    # 故检测在切过的掩膜上做(边界伪影照样清掉),但形状要回查它所属的
    # **完整**连通域——那样量到的才是真实形状(实测同一条渗水:切过时
    # elong=13.85,完整时 14.31;而边界伪影完整时只有 rect=0.67 elong=1.91,
    # 自然被形状规则挡住,不会把边界切出来的直边当成矩形)。
    labels = {k: cv2.connectedComponents(v.astype(np.uint8), connectivity=8)[1]
              for k, v in full.items()} if dp.border_ignore_px > 0 else {}

    # |拉普拉斯| 全图每帧只算一次,供全部斑块复用(extract_features 默认每斑块重算)
    lap = np.abs(cv2.Laplacian(T, cv2.CV_32F))
    sharp_ref = float(lap.mean())

    defects: List[Defect] = []
    for sign in ("warm", "cold"):
        seen = set()
        for blob in detect.extract_blobs(masks[sign], dp.min_area_px):
            m, bbox, area = blob["mask"], blob["bbox"], blob["area"]
            if labels:
                lab = int(labels[sign][tuple(np.argwhere(m)[0])])
                if lab in seen:
                    continue  # 同一完整连通域被边界带切成两段,只报一次
                seen.add(lab)
                m = labels[sign] == lab
                x, y, w, h = cv2.boundingRect(m.astype(np.uint8))
                bbox, area = (x, y, w, h), int(m.sum())
            f = feat_mod.extract_features(m, T, fp.ring_kernel,
                                          lap_map=lap, sharp_ref=sharp_ref,
                                          bbox=bbox)
            label = classify.classify(f, sign, cp_eff)
            # 渗漏保护(本项目新增,算法在 seepage_guard.py):形状渗漏规则不看 ΔT,
            # "细长的冷东西"一律判渗漏;实测 test04 上那批窗间墙柱/横向接缝就栽在
            # 这里(边缘规整度 0.71~1.00,是人造直边物)。边缘太直的改判非缺陷。
            sv = seepage_guard.reconsider(label, m)
            if sv.changed:
                print("[info] 渗漏保护:斑块 bbox=%s %s → %s(%s)"
                      % (tuple(int(v) for v in bbox), label, sv.label, sv.reason))
            label = sv.label
            area_m2 = float(area) * g ** 2 if g else None
            defects.append(Defect(sign=sign, label=label, area_px=area,
                                  bbox=bbox, mask=m, features=f, area_m2=area_m2))
    # 第二遍检测后按掩膜覆盖率排除残留:过渡带角部可能残留零点几度的冷缝,
    # 被修复/检测放大成贴着掩膜边的候选斑块——与掩膜覆盖率超过阈值即排除
    # (exclude_overlap 是原设计口径,打印排除计数)
    if win_mask is not None:
        kept = [d for d in defects
                if not _masked_out(d.mask, win_mask, wm.exclude_overlap)]
        if len(kept) != len(defects):
            print("[info] 窗户掩膜:第二遍排除 %d 处与掩膜重叠的候选"
                  % (len(defects) - len(kept)))
        defects = kept
    return T, window_defects + defects


def run_on_path(path, params: Params, warnings: Optional[list] = None,
                debug: Optional[dict] = None) -> Tuple[np.ndarray, List[Defect]]:
    """读取输入文件并执行方案一管线。返回 (校正后的温度矩阵, 缺陷列表)。

    warnings:可选列表,输入降级(如灰度伪温度回退)时追加记录,供
    save_results 写入 summary.json。
    debug:可选字典,转发给 run_single,承接调试产物(绝对矩形掩膜)。
    """
    T = read_temperature(path, warnings=warnings)
    return run_single(T, params, debug=debug)


# ---------------------------------------------------------------- 输出

def render_overlay(T: np.ndarray, defects: List[Defect],
                   disp: Optional[DisplayParams] = None) -> np.ndarray:
    """温度伪彩 + 缺陷轮廓 + 标签,用于人工复核。

    disp 为显示过滤(None=不过滤,即全画)。只影响本图:被过滤的斑块仅跳过
    绘制,不重新编号,编号沿用斑块在 defects 中的下标,与 defects.csv 的
    index 列、mask_NNN_*.png 的 NNN 一一对应(故隐藏后编号可能不连续)。
    过滤口径见 config.DisplayParams。
    """
    lo, hi = np.percentile(T, 2), np.percentile(T, 98)
    t = np.clip(T, lo, hi)
    t = (t - lo) / max(hi - lo, 1e-6)
    img = cv2.applyColorMap((t * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    colors = {"hollow": (0, 0, 255), "seepage": (255, 0, 0),
              "window": (0, 255, 255), "reject": (255, 255, 255)}
    for i, d in enumerate(defects):
        if disp is not None and not disp.shows(d.label, d.bbox):
            continue  # 只跳过绘制:编号仍与 defects.csv / mask 对齐
        cnts, _ = cv2.findContours(d.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cnts, -1, colors[d.label], 2)
        x, y, _, _ = d.bbox
        cv2.putText(img, "%d:%s" % (i, d.label), (x, max(y - 6, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[d.label], 1, cv2.LINE_AA)
    return img


def save_results(out_dir, out_final, name: str, T: np.ndarray, defects: List[Defect], params: Params,
                 scheme: str = "single",
                 warnings: Optional[list] = None,
                 debug: Optional[dict] = None) -> Path:
    """输出:温度矩阵、伪彩叠加图、**修复前标注图**、斑块掩膜、缺陷清单 CSV、
    汇总 JSON(含参数快照)。

    defects.csv 的 component 列与 summary.json 的 defects[].component 为单帧
    管线惰性默认值(始终为空),字段保留以兼容输出格式。

    debug:run_single 的出参。含 "T_preinpaint"(校正+去噪后、修复前的温度快照)
    时,在 final/<name>/ 另写一张 overlay_preinpaint.png——底图是窗户还没被填掉的
    原画面,标注与 overlay.png 完全一致(实现见 preinpaint_overlay.py);取不到
    快照就跳过(不拿处理后的矩阵顶替)。含 "rect_mask" 时额外写 rect_mask.png 并把
    矩形清单并入 summary.json。**未启用时会删掉上一次遗留的 rect_mask.png**:
    本函数从不清理输出目录(既有问题),不删的话上一轮开启时的产物会留下来
    让人误判本次也跑了。
    """
    out = Path(out_dir) / name
    out_final = Path(out_final) / name

    out.mkdir(parents=True, exist_ok=True)
    out_final.mkdir(parents=True, exist_ok=True)

    np.save(str(out / "temperature.npy"), T)
    cv2.imwrite(str(out_final / "overlay.png"), render_overlay(T, defects, params.display))
    # 修复前标注图(本项目新增):与 overlay.png 同目录,底图取"窗户还在"的那一版
    preinpaint_overlay.save(out_final, name, (debug or {}).get("T_preinpaint"),
                            defects, params)
    for i, d in enumerate(defects):
        cv2.imwrite(str(out / ("mask_%03d_%s.png" % (i, d.label))), d.mask.astype(np.uint8) * 255)

    # 调试图:名字必须是 rect_mask.png —— 不能叫 mask_*.png,否则会被
    # tests/test_pipeline.py 的 glob("mask_*.png") == len(defects) 断言算进去。
    # 写的是**修复前的检测掩膜**,好把"检测错"和"生长错"分开看。
    rmask = (debug or {}).get("rect_mask")
    if rmask is not None:
        cv2.imwrite(str(out / "rect_mask.png"), rmask.astype(np.uint8) * 255)
    else:
        stale = out / "rect_mask.png"
        if stale.exists():
            stale.unlink()

    with open(out / "defects.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "sign", "label", "area_px", "area_m2",
                    "x", "y", "w", "h",
                    "dT_c", "sharp", "uniform", "rect", "elong", "verticality",
                    "source", "component"])
        for i, d in enumerate(defects):
            x, y, ww, hh = d.bbox
            f = d.features
            area_m2 = round(d.area_m2, 4) if d.area_m2 is not None else ""
            component = (d.component + 1) if d.component is not None else ""  # 1-based
            w.writerow([i, d.sign, d.label, d.area_px, area_m2, x, y, ww, hh,
                        round(f["dT"], 3), round(f["sharp"], 3), round(f["uniform"], 3),
                        round(f["rect"], 3), round(f["elong"], 3), round(f["verticality"], 3),
                        d.source, component])

    counts = {}
    for d in defects:
        counts[d.label] = counts.get(d.label, 0) + 1
    summary = {
        "input": name,
        "scheme": scheme,
        "params": params.to_dict(),
        "counts": counts,
        "defects": [
            {"sign": d.sign, "label": d.label, "area_px": d.area_px,
             "area_m2": d.area_m2, "bbox": list(d.bbox),
             "source": d.source,
             "component": (d.component + 1) if d.component is not None else None,
             "comp_kind": d.comp_kind,
             "features": {k: (round(v, 4) if isinstance(v, float) else v)
                          for k, v in d.features.items()}}
            for d in defects
        ],
    }
    if warnings:
        summary["warnings"] = warnings
    if debug and debug.get("rects") is not None:
        summary["rect_mask"] = {
            "count": len(debug["rects"]),
            "note": "调试用绝对矩形掩膜;count 不等于窗户个数(窗内有暖色窗框时一个窗会裂成 4 个四边)",
            "rects": debug["rects"],
        }

    with open(out / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return out
