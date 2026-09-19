"""渗漏保护:边缘太直的"渗漏"其实是人造直边物,改判为非缺陷(**本项目新增**)。

**本模块是纯新增文件**:`classify.py` 一行未改(形状渗漏规则仍在原处),只在
`pipeline.run_single` 里拿到 `label` 之后插了几行调用 `reconsider()`。

## 要解决什么(test04 实测)

`classify.py` 的**形状渗漏规则**(C 节引入)是"矩形度高 + 细长即判渗漏,**不看 ΔT**"——
它抓形状确定的规则渗水很有效,但对"细长的冷东西"一视同仁。实测 test04 输出 12 个
`seepage`,用户给的真值是:**只有最右侧那一条是真渗漏**,其余 10 个是**窗间墙柱与
横向接缝**这类人造直边物:

```
(258,53,14,109) (65,55,18,105) (159,54,18,107)    ← 竖向墙柱,一根排一根
(62,271,20,132) (157,272,18,131) (255,273,15,130)
(0,50,48,4) (0,264,51,5) (98,266,48,3) (280,267,52,4)  ← 横向接缝
```

## 判据:边缘太直 → 不是自然蔓延的渗水

用 `window_guard` 的口径③(**同一份实现**,免得两处漂):把物体摆正后取两条长边,
量它们相对各自最小二乘直线的**平均偏离(px)**与**超容差偏差的占比**,合成
`regularity ∈ [0,1]`。自然渗水是**毛边**的,人造直边物是**直边**的:

| 物体 | 偏离直线 | 规整度 | 判定 |
|---|---|---|---|
| test04 六根窗间墙柱(人造直边) | 0.13~0.29px | 0.71~1.00 | **改判非缺陷** |
| test04 唯一真渗漏 (380,274,10,30) | 0.68px | 0.30 | 维持渗漏 |
| test02 左柱(真渗漏,现由窗户保护判渗漏) | 1.96px | 0.00 | 维持渗漏 |
| test04 (178,243,93,29) 冷斑 | 1.56px | 0.00 | 维持渗漏(它是 ΔT 规则判的假阳性,本模块管不了) |

## 细线也判(`min_short_px` 默认 0)

细线(几 px 高)在本口径下"两条长边"模型是退化的——上沿下沿几乎重合,量出来的偏差
自然小。**但退化不代表该放过**:细长的冷线在实测里就是**窗户隔板、横向接缝**这类人造
构造,不是自然蔓延的渗水。

这一条踩过一次坑,如实记下:本模块最初默认 `min_short_px = 5.0`,为的是保护
**test01 那条 2px 水平线**(bbox 306,120,26,3,dT −1.74)——当时依据的是项目笔记
"唯一的真渗水是水平的"。**用户后来更正:那条 2px 线是窗户的隔板,是假渗水**。
于是宽度门槛的前提没了:默认改成 **0(细线也判)**,那条线连同 test04 的四条
3~5px 横向接缝一起被改判(实测它们的规整度 0.574~0.897,都在门槛之上)。

`min_short_px` 这个旋钮保留(现场若发现某类细线该放过,抬上去即可),但**默认不网开一面**。

## 参数住在哪

`config/defaults.yaml` 的 `seepage_guard:` 段(与主参数同一份文件),**由本模块自行
读取、不经过 `Params`**(`config.py` 一行未动,与 `window_guard` 同款)。段内
`enabled` 就是用户要的那个开关。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import config as cfg
from . import window_guard

_YAML_SECTION = "seepage_guard"


@dataclass
class SeepageGuardParams:
    """渗漏保护参数(本模块自带;YAML 见 config/defaults.yaml 的 seepage_guard 段)。"""

    enabled: bool = True         # 开关(用户要求放 defaults.yaml):false=不做任何改判
    regular_min: float = 0.50    # 边缘规整度 ≥ 此值 → 像人造直边物 → 改判非缺陷。
                                 # 实测 人造直边物 0.71~1.00、毛糙渗漏 0.00~0.30
    min_short_px: float = 0.0    # 短边 < 此值不判。默认 0 = 细线也判:实测细长冷线
                                 # 是窗户隔板/横向接缝(人造构造),不是渗水。
                                 # 曾经默认 5.0,为保护 test01 那条 2px 线——那条被
                                 # 用户更正为窗户隔板后,这个前提没了(见模块 docstring)
    edge_dev_ref_px: float = 1.0  # 边缘口径的两个参数,与 window_guard 同口径同默认
    edge_tol_px: float = 2.0     # (有用例钉住两处默认一致)
    # classify.py 里那两条**渗水鉴定规则**的总开关(classify.py 一行未改,靠
    # effective_classify_params() 把阈值推到不可能达到来实现,见那里的说明):
    shape_rule_on: bool = True   # 形状渗漏规则(rect>0.80 且 elong>2.0,不看 ΔT)
    dt_rule_on: bool = True      # ΔT 渗漏规则(dT<seepage_dt_c 且 elong>seepage_elong)
    # 边缘口径的两个子口径,各自可开关(用户要求拆开):合规整度 = 开着那几项的乘积,
    # 两项都关 = 恒判"规整"(等于全部改判)——要关整条规则请用上面的 enabled
    line_on: bool = True         # 子口径①:上/下沿到最小二乘直线的平均偏离(边直不直)
    prot_on: bool = True         # 子口径②:偏离超容差的占比(不规则突出占多大比例)

    def __post_init__(self):
        for name in ("enabled", "shape_rule_on", "dt_rule_on", "line_on", "prot_on"):
            v = getattr(self, name)
            if isinstance(v, bool):
                continue
            if isinstance(v, int) and v in (0, 1):
                setattr(self, name, bool(v))    # YAML 里写 0/1 也认
                continue
            raise ValueError("seepage_guard 的 %s 必须为 true/false(或 0/1),当前为 %r"
                             % (name, v))


def effective_classify_params(cp):
    """把"渗水鉴定"两条规则的开关落到一份 classify 参数上;两条都开着时原样返回。

    **为什么是"推阈值"而不是加字段**:那两条规则住在 `classify.py` 里(既有算法文件,
    按用户要求不动),`ClassifyParams` 也动不得——所以开关只能从外面把对应阈值推到
    **不可能达到**的值:

        形状规则:`seepage_rect = +inf`(rect 是面积/最小外接矩形面积,理论上 ≤ 1,
                  但实测 OpenCV 最小外接矩形取整后会到 1.04,所以不能用 1.01 这种
                  "贴着上界"的值——第一次就栽在这儿:1.04 > 1.01,规则照旧成立)
        ΔT 规则:`seepage_dt_c = -inf`(温差不可能低于它)

    这样关掉的规则**永不成立**,而 `classify.py` 一个字没改。返回的是**副本**(都开着
    时返回原对象,零开销),不动调用方手里那份 params——`summary.json` 的参数快照
    因此仍是用户写在 YAML 里的真值,不会被这个开关悄悄改写。
    """
    gp = current_params()
    if gp.shape_rule_on and gp.dt_rule_on:
        return cp
    c = copy.copy(cp)
    if not gp.shape_rule_on:
        c.seepage_rect = float("inf")
    if not gp.dt_rule_on:
        c.seepage_dt_c = float("-inf")
    return c


@dataclass
class ReconsiderVerdict:
    """一次改判的结果(供调用方决定最终标签与是否打印)。"""

    label: str                    # 最终标签(未改判时就是传进来的那个)
    changed: bool                 # 是否改判了
    short_px: float = 0.0         # 物体的短边(px)
    regularity: float = 0.0       # 边缘规整度(未量到时为 0)
    reason: str = ""              # 一句话理由(打印/追溯用)


def short_side(mask: np.ndarray) -> float:
    """短边长度(px):最小外接矩形的短边,与 `window_guard.elongation` 同口径。"""
    pts = np.argwhere(mask).astype(np.int32)
    if len(pts) < 4:
        _, _, w, h = cv2.boundingRect(mask.astype(np.uint8))
        return float(min(w, h))
    _, (ma, mi), _ = cv2.minAreaRect(pts)
    return float(min(ma, mi))


def reconsider(label: str, mask: np.ndarray,
               gp: Optional[SeepageGuardParams] = None) -> ReconsiderVerdict:
    """把"边缘太直"的渗漏改判为非缺陷(reject);其余一律原样返回。

    只动 `label == "seepage"` 的:其它标签、保护关闭、物体太细(短边 < min_short_px)、
    边缘确实毛糙 —— 四种情况都沿用原判。
    """
    gp = gp if gp is not None else current_params()
    if not gp.enabled:
        return ReconsiderVerdict(label=label, changed=False, reason="渗漏保护已关闭")
    if label != "seepage":
        return ReconsiderVerdict(label=label, changed=False, reason="非渗漏")

    short = short_side(mask)
    if short < gp.min_short_px:
        return ReconsiderVerdict(label=label, changed=False, short_px=short,
                                 reason="短边 %.1fpx < %.1f,细线不判" % (short, gp.min_short_px))

    reg = window_guard.regularity(mask, gp.edge_dev_ref_px, gp.edge_tol_px,
                                  line_on=gp.line_on, prot_on=gp.prot_on)
    fit = window_guard.edge_fit_detail(mask, gp.edge_tol_px)
    used = ("直线拟合+突出占比" if (gp.line_on and gp.prot_on) else
            "只算直线拟合" if gp.line_on else
            "只算突出占比" if gp.prot_on else "两个子口径都关着")
    tail = "(偏离直线 %.2fpx、突出占比 %.3f;%s)" % (fit["dev_px"], fit["prot_frac"], used)
    if reg >= gp.regular_min:
        return ReconsiderVerdict(
            label="reject", changed=True, short_px=short, regularity=reg,
            reason=("短边 %.1fpx,边缘规整度 %.3f ≥ %.2f%s——人造直边物,不是渗漏"
                    % (short, reg, gp.regular_min, tail)))
    return ReconsiderVerdict(
        label=label, changed=False, short_px=short, regularity=reg,
        reason=("短边 %.1fpx,边缘毛糙(规整度 %.3f < %.2f)%s,维持渗漏"
                % (short, reg, gp.regular_min, tail)))


# ---------------------------------------------------------------- 参数装载

_PARAMS_CACHE: Optional[SeepageGuardParams] = None


def default_yaml_path() -> Path:
    """仓库里的 config/defaults.yaml(与 window_guard 读的是同一份)。"""
    return window_guard.default_yaml_path()


def from_yaml(path=None) -> SeepageGuardParams:
    """从 YAML 的 `seepage_guard:` 段读参数;文件或该段缺失时用代码默认。

    键名写错照主配置的严格口径报错(复用 config._build),不静默回退默认。
    """
    p = Path(path) if path is not None else default_yaml_path()
    if not p.exists():
        return SeepageGuardParams()
    import yaml as _yaml
    with open(p, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh) or {}
    section = raw.get(_YAML_SECTION)
    if section is None:
        return SeepageGuardParams()
    return cfg._build(SeepageGuardParams, section, _YAML_SECTION)


def current_params(path=None) -> SeepageGuardParams:
    """当前生效的参数(缓存)。

    优先级:显式 `set_params()` > `path` 出参 > 环境变量
    THERMAL_INSPECT_SEEPAGE_GUARD 指向的 YAML > 仓库 config/defaults.yaml 的
    `seepage_guard` 段 > 代码默认。现场调参后重跑进程即可生效。
    """
    global _PARAMS_CACHE
    if _PARAMS_CACHE is not None:
        return _PARAMS_CACHE
    import os
    env = os.environ.get("THERMAL_INSPECT_SEEPAGE_GUARD")
    _PARAMS_CACHE = from_yaml(path or env or default_yaml_path())
    return _PARAMS_CACHE


def set_params(gp: Optional[SeepageGuardParams]) -> Optional[SeepageGuardParams]:
    """显式覆盖参数(None=清空缓存,恢复按文件装载);返回传入值,便于链式调用。"""
    global _PARAMS_CACHE
    _PARAMS_CACHE = gp
    return gp
