"""通用红外图片读取:把"非大疆"的红外图片读成温度矩阵(**本项目新增**)。

**本模块是纯新增文件**:`io.py`(大疆 R-JPEG 读取)、`preprocess.py`、`detect.py`、
`pipeline.py` 等**一行未改**。接线方式沿用 `border_fill` 那套插件做法:

    T = ir_reader.read_ir(某红外图, calib)      ← 本模块,产出 ℃ 矩阵
    T, defects = run_single(T, params)            ← 原样的管线,一行没动
    save_results(...)                             ← 原样的输出

也就是说:本模块只负责**把各种红外图片翻译成"摄氏度矩阵"**,翻译完之后,后面
整条管线(去趋势 → MAD → z 阈值 → 特征 → 规则分类)照常工作。

## 为什么"能不能用"取决于标定

管线的判据分两类(逐层核过):

| 判据 | 依赖 | 换设备后 |
|---|---|---|
| 去趋势 / MAD / z 分数 / 检测阈值 | **纯相对** | 不用改 |
| 全部形状判据(矩形度/伸长率/边缘规整度/锐度) | **像素几何** | 完全无关 |
| `dT` 的**定义**(斑块均值 − 外环带均值) | **相对** | 不用改 |
| `dT` 的**阈值**(空鼓 1.5℃ / 渗水 −1.5℃ / 窗户 −5.0℃ …) | **绝对摄氏度** | ⚠ **必须重标** |

所以本模块的目标是:**把像素值翻译成尽可能接近真实的摄氏度**,让那些 ℃ 阈值
至少在量级上说得通;至于阈值要不要按新设备重调,那是现场标定的事(见文末)。

## 三种读取模式

| mode | 输入 | 做法 | 精度 |
|---|---|---|---|
| `matrix` | `.npy` / 16bit TIFF(温度矩阵或灰度原始数据) | 直接当温度用;灰度按 `t_min~t_max` 线性映射 | **最好**(无颜色量化损失) |
| `gray` | 单通道灰度热图 | `T = t_min + v/255 × (t_max − t_min)` | 看位深(8bit 差、16bit 好) |
| `palette` | 伪彩色热图(JPG/PNG) | 反查调色板:每个像素颜色 → 最接近的色阶序号 → 归一化 → 线性映射 | **最差**,见下 |

## 用 `palette` 模式前必须知道的四件事

1. **必须知道量程**(`t_min` / `t_max`):同一个颜色,量程 10~40℃ 时是 25℃,
   量程 20~120℃ 时是 70℃。量程不对,整张图的温度全错。
2. **必须知道调色板**(`colormap`):各厂家"铁红"的色阶并不完全相同。本模块内置
   OpenCV 的几种常见色表(iron/rainbow/jet/inferno/gray 等);**若能拿到该设备
   导出的色标条图片,可以自己采样建表**(见 `colormap_from_bar`)。
3. **AGC 是最大的坑**:消费级热像仪会**自动伸缩量程**让画面好看,而且通常不把
   实际量程写进图里。同一面墙早上和下午拍的,同一个颜色可能差好几度。若设备能
   关掉 AGC(固定量程)再拍,务必关掉。
4. **8bit + JPEG 的量化**:8bit 只有 256 级,量程 100℃ 时每级 ≈ 0.39℃——而空鼓
   判据要 1.5℃,**只剩 4 级分辨率**;叠加 JPEG 的色度子采样压缩后误差还会更大。
   实测参考见 `logs/修改日志.md`。

**结论**:`palette` 模式给的是"近似温度",足以做相对分布分析(形状判据、z 分数
判据都还能用),但 **℃ 阈值必须按新设备重新标定**,不能直接沿用大疆那套。

## 实测数据(2026-10-04,`logs/修改日志.md` S 节)

**闭环精度**(温度矩阵 → 渲染伪彩 → 本模块反演 → 比对;demo 场景,量程 12.1℃,
一个色阶 = 0.047℃):

| 格式 | 最大误差 | 平均误差 | 说明 |
|---|---|---|---|
| PNG(无损) | **1.0 色阶** | 0.5 色阶 | 已经到 8bit 量化极限,不能再好 |
| JPEG(默认/95) | **28 色阶(1.32℃)** | 1.9 色阶 | JPEG 色度子采样在颜色突变处产生色晕 |
| JPEG 75 | 36 色阶(1.69℃) | 2.4 色阶 | 质量再降,个别像素更离谱 |

⚠ **JPEG 的最大误差已接近空鼓判据 1.5℃**。所以:能用 PNG/TIFF 就别用 JPEG;
非要用 JPEG,就要知道会有少量像素偏出去几十个色阶。

**真实数据**(`dataset/` 的 2348 张 1280×1024 热成像图):配色匹配度实测
**rainbow = 142**,而 jet = 4404、turbo = 4796、hot = 10289 —— 那批图用的是
**rainbow**,不是常见的"铁红"。**色表选错代价极大**:同一张图 rainbow 反演检出
78 处,jet 反演只剩 12 处(温度整体算错)。

## ⚠ 用之前必须确认:缺陷的"符号"

`CLAUDE.md` 里那句"**空鼓的符号随时相翻转**"不是理论——实测那批数据集里
**11 个标注框的 dT 全是负的**(−0.54 ~ −3.98℃,中位 **−0.96℃**):降温时段
(傍晚/夜间/阴天)空鼓散热比实体墙快,在热像图上表现为**冷斑**,与白天升温时的
热斑**方向相反**。

而现有判据找的是**热斑**(`hollow_dt_c = +1.5℃`)。所以换一批数据前,先问:
**这批是什么时段拍的?缺陷该是热还是冷?** 拿几个已知缺陷量一下 dT 的**符号**,
比调阈值重要得多。


## 参数住在哪

本模块自带 `IrCalibParams`(代码默认),并**可选**从 `config/defaults.yaml` 的
`ir_reader:` 段读取——该段**不需要存在**,缺失时用代码默认(故 `defaults.yaml`
一行未改)。键名写错仍按主配置的严格口径报错。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import config as cfg

# OpenCV 调色板名 → 常量。**厂家色表与这些未必逐位相同**,能用色标条自采就用自采。
_CMAP_IDS = {
    "iron": cv2.COLORMAP_JET,        # 最常见的"铁红"近似
    "jet": cv2.COLORMAP_JET,
    "rainbow": cv2.COLORMAP_RAINBOW,
    "inferno": cv2.COLORMAP_INFERNO,  # 本项目 overlay 用的就是它
    "turbo": cv2.COLORMAP_TURBO,
    "hot": cv2.COLORMAP_HOT,
    "bone": cv2.COLORMAP_BONE,
    "whitehot": cv2.COLORMAP_BONE,   # 近似;真正的白热是纯灰,用 colormap="gray"
    "gray": cv2.COLORMAP_BONE,       # 占位,纯灰走 _palette_refs 里的特判
}

_INVERT_HINT = ("黑白热反了?把 colormap 换成 gray 并把 invert 打开,"
                "或直接换成另一个色表名")

_CHUNK = 8192   # 反查调色板时的分块大小(控内存:块 × 256 色 × 3 通道)


@dataclass
class IrCalibParams:
    """通用红外图的标定参数(本模块自带;YAML 见 config/defaults.yaml 的 ir_reader 段)。

    **没有量程就没有温度**:`t_min` / `t_max` 是这个模块最要紧的两个数。
    """

    mode: str = "gray"        # 'gray' 单通道灰度 | 'palette' 伪彩 | 'matrix' 温度矩阵
    t_min: float = 10.0       # 量程下限(℃):图中"最冷那个色阶"对应的温度
    t_max: float = 40.0       # 量程上限(℃):图中"最热那个色阶"对应的温度
    colormap: str = "iron"    # palette 模式的色表名(见 _CMAP_IDS),或 'custom'
    palette_file: Optional[str] = None  # colormap='custom' 时的色表图(色标条)路径
    invert: bool = False      # 色阶方向反了时打开(白热↔黑热)
    invert_gray: bool = False  # gray 模式专用:0=最冷 → 反向

    def __post_init__(self):
        if self.mode not in ("gray", "palette", "matrix"):
            raise ValueError("ir_reader 的 mode 必须为 'gray' / 'palette' / 'matrix',"
                             "当前为 %r" % (self.mode,))
        if not isinstance(self.t_min, (int, float)) or not isinstance(self.t_max, (int, float)):
            raise ValueError("ir_reader 的 t_min / t_max 必须是数值(℃),当前为 %r / %r"
                             % (self.t_min, self.t_max))
        if float(self.t_max) <= float(self.t_min):
            raise ValueError("ir_reader 的 t_max(%.3f)必须大于 t_min(%.3f):"
                             "量程反了,温度会整体算错" % (self.t_max, self.t_min))
        if self.mode == "palette" and self.colormap != "custom" \
                and self.colormap not in _CMAP_IDS:
            raise ValueError("ir_reader 的 colormap 必须为 %s 或 'custom',当前为 %r"
                             % (" / ".join(sorted(_CMAP_IDS)), self.colormap))


# ---------------------------------------------------------------- 文件读写

def _imread_unicode(path, flags=cv2.IMREAD_COLOR):
    """读图,**支持中文等非 ASCII 路径**。

    为什么不用 `cv2.imread`:实测 OpenCV 5.0.0(Windows)对非 ASCII 路径**读不到**
    (返回 None),而且 `cv2.imwrite` 更危险——**返回 True 却根本没写文件**(静默失败)。
    用 `np.fromfile` + `cv2.imdecode` 绕开这条系统调用路径,中英文名都可靠。

    (既有模块 io.py / pipeline.py 也用了 cv2.imread/imwrite,同样受此影响;按"不动
    既有代码"的约定,这里只在新模块里规避,那条另记在 logs/修改日志.md。)
    """
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def _imwrite_unicode(path, img) -> bool:
    """写图,**支持中文等非 ASCII 路径**(与 `_imread_unicode` 配套)。

    `cv2.imwrite` 在 OpenCV 5.0 + Windows + 中文路径下会**假装成功**(返回 True、
    文件不存在),必须先 `imencode` 再 `tofile` 才可靠。本模块目前不写图,这个函数
    留给调用方复用(例如将来给别人写"读通用红外图"的脚本)。
    """
    ext = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    try:
        buf.tofile(str(path))
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- 调色板

def _palette_refs(name: str, palette_file: Optional[str] = None) -> np.ndarray:
    """返回 (256, 3) 的 BGR 参考色表(索引 0 = 最冷,255 = 最热)。"""
    if name == "custom":
        if not palette_file:
            raise ValueError("colormap='custom' 必须同时给 palette_file(色标条图片路径)")
        return colormap_from_bar(palette_file)
    if name == "gray":
        v = np.arange(256, dtype=np.uint8)
        return np.stack([v, v, v], axis=1)          # BGR 三通道相同
    ramp = np.arange(256, dtype=np.uint8).reshape(1, 256)
    return cv2.applyColorMap(ramp, _CMAP_IDS[name])[0]


def colormap_from_bar(path, n: int = 256, axis: str = "vertical") -> np.ndarray:
    """从**色标条**图片采样出参考色表(比猜厂家色表准得多)。

    用法:把设备导出图上那条色标(半路有个温度刻度的彩条)裁剪下来存成小图,
    传给本函数即可。返回 (n, 3) BGR,索引 0 = 最冷端。

    `axis='vertical'` 表示色标条竖直(默认,多数设备如此);色标条若是横放的
    改 'horizontal'。采样时取每条的中心线并做一维中值,避开刻度文字与边框。
    """
    img = _imread_unicode(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError("读不到色标条图片: %s" % path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 去掉靠近纯黑/纯白的像素(边框、刻度文字),它们不代表色阶
    keep = (gray > 8) & (gray < 247)
    if axis == "vertical":
        h, w = img.shape[:2]
        cols = [x for x in range(w) if keep[:, x].mean() > 0.6]
        if not cols:
            raise ValueError("色标条里找不到有效色阶列(全是边框/文字?): %s" % path)
        band = img[:, cols[0]:cols[-1] + 1]
        prof = np.median(band, axis=1)                       # (h, 3)
    else:
        h, w = img.shape[:2]
        rows = [y for y in range(h) if keep[y, :].mean() > 0.6]
        if not rows:
            raise ValueError("色标条里找不到有效色阶行(全是边框/文字?): %s" % path)
        band = img[rows[0]:rows[-1] + 1, :]
        prof = np.median(band, axis=0)                       # (w, 3)
    if prof.shape[0] < 8:
        raise ValueError("色标条太短(%d 个采样点),换一张更长的" % prof.shape[0])
    idx = np.linspace(0, prof.shape[0] - 1, n)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, prof.shape[0] - 1)
    frac = (idx - lo)[:, None]
    return (prof[lo] * (1 - frac) + prof[hi] * frac).astype(np.uint8)


def _invert_palette(img_bgr: np.ndarray, refs: np.ndarray,
                    chunk: int = _CHUNK) -> np.ndarray:
    """把伪彩图反查成 0~1 的归一化值(每像素找最接近的参考色阶)。

    分块做,避免 (像素数 × 256 × 3) 一次性展开(640×512 的图那样要 ~1.5 GB)。
    """
    h, w = img_bgr.shape[:2]
    flat = img_bgr.reshape(-1, 3).astype(np.int16)
    refs_i = refs.astype(np.int16)
    out = np.empty(flat.shape[0], dtype=np.float32)
    for i in range(0, flat.shape[0], chunk):
        blk = flat[i:i + chunk]
        d = ((blk[:, None, :].astype(np.int32)
              - refs_i[None, :, :].astype(np.int32)) ** 2).sum(axis=2)
        out[i:i + chunk] = d.argmin(axis=1)
    return (out / 255.0).reshape(h, w).astype(np.float32)


# ---------------------------------------------------------------- 主入口

def _read_gray(path) -> np.ndarray:
    """读单通道。16bit TIFF 原样保留(0~65535),8bit 图是 0~255。"""
    img = _imread_unicode(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError("读不到图片: %s" % path)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def read_ir(path, p: Optional[IrCalibParams] = None,
            warnings: Optional[list] = None) -> np.ndarray:
    """把一张通用红外图片读成温度矩阵(℃,float32)。

    返回的是**表观温度**(相机读到什么就是什么),与 `io.read_temperature` 的契约
    一致——发射率校正这一层照旧由管线的 `preprocess.correct_emissivity` 负责,
    本模块不重复做。

    p 为 None 时用 `current_params()`(先看 defaults.yaml 的 `ir_reader:` 段,
    没有该段就用代码默认)。

    warnings 与 io.read_temperature 同款:追加一条"读到了什么、精度如何"的记录,
    供 save_results 写进 summary.json。
    """
    p = p if p is not None else current_params()
    path = Path(path)
    suffix = path.suffix.lower()

    if p.mode == "matrix" or suffix == ".npy":
        T = _read_matrix(path)
        note = "温度矩阵直读(%s)" % suffix
    elif p.mode == "gray":
        raw = _read_gray(path)
        T = _gray_to_temp(raw, p)
        note = "灰度热图线性映射(%d 级)" % (256 if raw.dtype == np.uint8 else 2 ** (raw.dtype.itemsize * 8))
    else:  # palette
        img = _imread_unicode(path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError("读不到图片: %s" % path)
        refs = _palette_refs(p.colormap, p.palette_file)
        norm = _invert_palette(img, refs)
        if p.invert:
            norm = 1.0 - norm
        T = (float(p.t_min) + norm * (float(p.t_max) - float(p.t_min))).astype(np.float32)
        note = ("伪彩反演(colormap=%s, 量程 %.1f~%.1f℃)"
                % (p.colormap, p.t_min, p.t_max))

    print("[info] 通用红外读取: %s | %s | %.2f~%.2f℃"
          % (path.name, note, float(T.min()), float(T.max())))
    if warnings is not None:
        warnings.append({
            "file": path.name, "level": "generic_ir", "reader": "ir_reader",
            "mode": p.mode, "note": note,
            "effect": ("非大疆设备:温标由用户给定的量程/色表换算而来;"
                       "以℃为单位的判据(空鼓 1.5℃ 等)需按本设备重新标定,"
                       "否则结论只可用于相对比较"),
        })
    return T.astype(np.float32)


def _read_matrix(path: Path) -> np.ndarray:
    """温度矩阵直读:.npy 或图片格式里的 16/32 位数据(当作 ℃ 用)。"""
    if path.suffix.lower() == ".npy":
        return np.load(str(path)).astype(np.float32)
    img = _imread_unicode(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError("读不到图片: %s" % path)
    if img.ndim == 3:                       # 彩色图当矩阵用没意义,明确报错
        raise ValueError("mode='matrix' 需要单通道的温度矩阵(.npy 或 16bit TIFF),"
                         "当前是 %d 通道的图片: %s。伪彩图请用 mode='palette'"
                         % (img.shape[2], path.name))
    return img.astype(np.float32)


def _gray_to_temp(raw: np.ndarray, p: IrCalibParams) -> np.ndarray:
    """灰度线性映射:0 → t_min,满量程 → t_max(按实际位深归一,16bit 也认)。"""
    if raw.dtype == np.uint8:
        full = 255.0
    elif raw.dtype == np.uint16:
        full = 65535.0
    else:
        full = float(raw.max()) if raw.max() > 0 else 1.0
    norm = raw.astype(np.float32) / full
    if p.invert_gray:
        norm = 1.0 - norm
    return (float(p.t_min) + norm * (float(p.t_max) - float(p.t_min))).astype(np.float32)


# ---------------------------------------------------------------- 参数装载

_PARAMS_CACHE: Optional[IrCalibParams] = None
_YAML_SECTION = "ir_reader"


def default_yaml_path() -> Path:
    """仓库里的 config/defaults.yaml(与 window_guard / seepage_guard 读同一份)。"""
    return Path(__file__).resolve().parents[2] / "config" / "defaults.yaml"


def from_yaml(path=None) -> IrCalibParams:
    """从 YAML 的 `ir_reader:` 段读参数;**该段不存在时用代码默认**(不报错)。

    `config/defaults.yaml` 里目前**没有**这一段(既有文件未改),所以默认走代码
    默认值;要用 YAML 管理这些参数,自己加一段即可,键名写错照样报错。
    """
    p = Path(path) if path is not None else default_yaml_path()
    if not p.exists():
        return IrCalibParams()
    import yaml as _yaml
    with open(p, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh) or {}
    section = raw.get(_YAML_SECTION)
    if section is None:
        return IrCalibParams()
    return cfg._build(IrCalibParams, section, _YAML_SECTION)


def current_params(path=None) -> IrCalibParams:
    """当前生效的参数(缓存);现场调参后重跑进程即可生效。"""
    global _PARAMS_CACHE
    if _PARAMS_CACHE is not None:
        return _PARAMS_CACHE
    import os
    env = os.environ.get("THERMAL_INSPECT_IR_READER")
    _PARAMS_CACHE = from_yaml(path or env or default_yaml_path())
    return _PARAMS_CACHE


def set_params(p: Optional[IrCalibParams]) -> Optional[IrCalibParams]:
    """显式覆盖参数(None=清空缓存);返回传入值,便于链式调用。"""
    global _PARAMS_CACHE
    _PARAMS_CACHE = p
    return p
