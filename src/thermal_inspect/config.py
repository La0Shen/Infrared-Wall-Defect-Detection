"""参数配置:内置默认值,可用 YAML 覆盖。对应 总体方案.md 第5节参数表。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import get_close_matches
from typing import Any, Dict, Optional, Union, get_args, get_origin, get_type_hints

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class PreprocessParams:
    """预处理参数(总体方案.md §1.2、§5)。"""

    emissivity: float = 0.90           # 发射率 ε,统一初值
    reflected_temp_c: float = 20.0     # 反射环境温度(℃)
    denoise_kernel: int = 3            # 中值滤波核尺寸(奇数)
    distance_m: Optional[float] = None  # 拍摄距离(m);填写后计算 GSD
    gsd_divisor: float = 540.0         # GSD ≈ 距离/540(Mavic 3T)


@dataclass
class DetectParams:
    """方案一检测参数(总体方案.md §2、§5)。"""

    detrend_sigma_px: float = 20.0    # 去趋势高斯模糊 σ(px)= 2~3 × 缺陷半径
    mad_scale: float = 1.4826         # MAD → 噪声标准差的比例系数
    z_threshold: float = 2.5          # z 分数阈值,|z| 超过即判为异常
    min_area_px: int = 25             # 最小斑块面积(px)
    border_ignore_px: int = 15        # 边界带宽度(px):照片最外 N px 视为墙,
                                      # 不参与检测;0=不过滤(旧行为)


@dataclass
class FeatureParams:
    """特征提取参数(总体方案.md §4)。"""

    ring_kernel: int = 5              # 外围环带膨胀核尺寸(px)


@dataclass
class ClassifyParams:
    """分类规则参数(总体方案.md §4)。

    定性条件(窗户"边界锐利"、空鼓"边界弥散"、渗水"长轴偏垂直")
    默认关闭,与 总体方案.md 伪代码一致;开启后与全图平均边缘锐度(sharp_ref)比较。
    """

    window_rect: float = 0.85            # 窗户:矩形度下限
    window_dt_c: float = -5.0            # 窗户:ΔT 上限(℃)
    window_require_sharp: bool = False    # 窗户:开启"边界锐利"条件
    hollow_dt_c: float = 1.5             # 空鼓:ΔT 下限(℃)
    hollow_rect: float = 0.8             # 空鼓:矩形度上限
    hollow_require_diffuse: bool = False  # 空鼓:开启"边界弥散"条件
    seepage_dt_c: float = -1.5           # 渗水:ΔT 上限(℃)
    seepage_elong: float = 1.5           # 渗水:伸长率下限
    seepage_require_vertical: bool = False  # 渗水:开启"长轴偏垂直"条件
    seepage_angle_tol_deg: float = 20.0  # 长轴与竖直方向夹角容差(°)
    # 形状渗漏规则(本项目新增,不在 总体方案.md §4):矩形度高 + 细长即判渗漏,
    # 不看 ΔT——规则的矩形形状比温差更能说明问题(实测 ΔT 阈值抓不到
    # 形状确定的规则渗水)。优先级在窗户之后、上方 ΔT 规则之前。
    seepage_rect: float = 0.80           # 形状渗漏:矩形度下限
    seepage_rect_elong: float = 2.0      # 形状渗漏:纵横比下限(取 minAreaRect
                                         # 长轴/短轴,即 features 的 elong,
                                         # 旋转不变;与上方 seepage_elong 是
                                         # 同一个量,只是分属两条规则)
    seepage_shape_require_cold: bool = False  # 形状渗漏:是否要求 ΔT 下限
    seepage_shape_dt_c: float = -0.8     # 形状渗漏:ΔT 上限(℃);仅上一行为
                                         # true 时生效。实测 test01 上启用可挡掉
                                         # 全部 6 个弱信号(真渗水 dT=-1.70,
                                         # 其余全 ≥-0.55),按现场情况决定是否开


@dataclass
class WindowMaskParams:
    """窗户掩膜参数:识别为窗户后,整个窗户区域不作为识别条件。

    第一遍从 z 冷侧用宽松阈值找窗户区域(反光使窗户温度不均、整体仅略冷
    于墙面,检测层阈值抓不到),形态学闭运算把打碎的区域合并成块;第二遍
    检测时落在掩膜内的候选斑块直接排除。
    """

    enabled: bool = True                # False=关闭掩膜(恢复旧行为)
    z_threshold: float = 1.5            # 冷掩膜 z 阈值(比检测层宽松;窗户整体仅略冷,
                                        # 1.5 才能把反光打碎的窗户合并成完整区域块)
    close_direct: int = 3               # 直接路径闭运算核:只填窗内反光孔洞,不合并相邻窗
    close_kernel: int = 11              # 块路径闭运算核:合并成排/成列的窗户区域块
    min_area_px: int = 1500             # 区域块最小面积(滤小碎块)
    dT_max_c: float = 0.1               # 块均值与图像中位数之差上限:只滤明显暖的
                                        # 去趋势边缘伪影(dT>+1);窗户反光强烈时
                                        # 整体可不偏冷,故上限设正
    rect_direct: float = 0.85           # 直接矩形路径:最小外接矩形度下限
    aspect_min: float = 0.15            # 块路径宽高比下限(与 aspect_max 互为倒数)
    aspect_max: float = 6.67            # 块路径宽高比上限。原为 0.08/12.5,不足以挡住
                                        # 细长条:原以为"渗水是实心细条 rect≈1",但实测
                                        # 有 rect 只有 0.44、宽高比却到 0.131(长/宽 7.6)
                                        # 的贯穿全画幅细长冷条被当成"窗户区域块"。真正的
                                        # 窗区块(成排/成列)宽高比在 2~3 附近,故收紧到
                                        # ±1/0.15;比这更细长的按渗漏交给检测层判
    block_aspect_lo: float = 0.5        # 块路径仅接受明显细长的块(宽高比 <0.5 或 >2.0):
    block_aspect_hi: float = 2.0        # 近方形的冷块多为去趋势伪影/普通冷区,不按窗户
    dilate_px: int = 2                  # 基础膨胀(盖住窗框)
    grow_tol_c: float = 0.2             # 过渡带生长停止:环带中位温度回到
                                        # "更外参考带 − grow_tol_c" 以上即停(℃);
                                        # 设小些把过渡带吃干净,残余≈本值
    grow_max_px: int = 10               # 过渡带生长步数上限(兜底防无界扩张;
                                        # 0=关闭自适应生长,仅用 dilate_px)
    exclude_overlap: float = 0.5        # 候选斑块与掩膜覆盖率超过此值即排除
    inpaint_radius: int = 3             # cv2.inpaint(NS) 修复半径(px):谐波延续
                                        # 背景填充;不用 Telea——它在过渡带斜坡
                                        # 边界上会产生 ±1℃ 棋盘纹,被下一段检测
                                        # 报成整片斑块


@dataclass
class DisplayParams:
    """叠加图显示参数:只控制 overlay.png 画哪些斑块。

    defects.csv / summary.json(含 counts)/ mask_NNN_*.png 一律为全量,不受
    本段影响(供复盘与追溯)。长度取轴对齐边框的 max(w, h)(px),不随旋转变化。
    """

    show_window: int = 1             # 窗户:1=显示,0=不显示
    show_hollow: int = 1             # 空鼓:1=显示,0=不显示
    show_seepage: int = 1            # 渗水:1=显示,0=不显示
    show_reject: int = 1             # 兜底未分类:1=显示,0=不显示
    min_len_window_px: int = 0       # 窗户:边框 max(w,h) 下限(px;0=全部显示)
    min_len_hollow_px: int = 0       # 空鼓:边框 max(w,h) 下限(px)
    min_len_seepage_px: int = 0      # 渗水:边框 max(w,h) 下限(px)
    min_len_reject_px: int = 0       # 兜底未分类:边框 max(w,h) 下限(px)

    def shows(self, label: str, bbox) -> bool:
        """该斑块是否画到 overlay.png(未知类别按显示处理)。"""
        flag = getattr(self, "show_" + label, 1)
        lo = getattr(self, "min_len_" + label + "_px", 0)
        return bool(flag) and max(bbox[2], bbox[3]) >= lo  # bbox=(x, y, w, h)


@dataclass
class RectMaskParams:
    """绝对矩形掩膜参数(**调试用**,本项目新增,不在 总体方案.md 内)。

    思路:直接对图片做**转码**——按"与全图中位数的绝对温差"转成二维二值矩阵,
    再对其中**规则粗边矩形**做掩埋处理。判据是**绝对**的(阈值是℃,不是 z 分数),
    不依赖噪声统计,也不做局部背景扣除。默认关闭,开着用来单独观察这套纯几何
    口径能抓到什么。

    规则 = 四边逼近恰 4 顶点 + 凸 + 四角近 90°;粗边 = 最粗处 ≥ min_edge_px。
    实心矩形与粗边框都算(判据是"边够粗",不是"必须是环形")。

    enabled 用 0/1 整数(与 display.show_* 同口径,且有 _check_rect_mask 严格校验);
    window_mask.enabled 是 bool —— 这处不一致是刻意的,别去"修"。
    浮点键(dt_c / approx_eps / angle_tol_deg / min_side_ratio)不做校验,
    与 z_threshold / rect_direct 等既有浮点参数同口径。
    """

    enabled: int = 0                 # 0=关闭(默认,行为与旧版逐字节一致),1=启用
    dt_c: float = 2.0                # 绝对温差(℃):|T − median(T)| > 此值即转成 1。
                                     # 本方法唯一的调节旋钮,取值影响很大:合成场景里
                                     # ΔT=−1.5℃ 的冷方块 dt=0.5 就完整找到;demo 场景
                                     # dt=3.0 恰好找到那个窗;真实帧 dt=1.0~3.0 给出
                                     # 几个矩形,二值占比从 26% 降到 10%
    morph_close: int = 3             # 转码后的闭运算核(补轮廓断口;0=不做)
    approx_eps: float = 0.05         # 四边逼近精度(占周长比例)。直接影响能否凑出
                                     # "恰 4 顶点":取 2% 时同一目标给出 6~10 个顶点
                                     # 而被否掉,取 5% 才收敛
    angle_tol_deg: float = 15.0      # 四角与 90° 的容差(°)
    min_area_px: int = 300           # 矩形最小面积(px)
    min_side_ratio: float = 0.15     # 短边/长边 下限(挡细长条,与 aspect_min 同口径)
    min_edge_px: float = 3.0         # 最小边宽(px):该矩形内前景像素到最近背景像素的
                                     # 最大距离 ×2(最粗处的宽度;直角处内切圆更大,
                                     # 角部会比带宽多 1~2px)。粗边框量到的是带宽、
                                     # 实心块量到的是短边。发丝细线也能凑出"恰 4 顶点",
                                     # 但不是粗边;0=不设门槛。实测 1px 细线 = 2.0px,
                                     # 真实窗框/实心块 = 14~92px,故 3.0 只挡细线
    dilate_px: int = 2               # 掩膜膨胀(px)
    inpaint_radius: int = 3          # NS 修复半径(px),同 window_mask


@dataclass
class Params:
    """全部参数(方案一单帧管线)。"""

    preprocess: PreprocessParams = field(default_factory=PreprocessParams)
    detect: DetectParams = field(default_factory=DetectParams)
    features: FeatureParams = field(default_factory=FeatureParams)
    classify: ClassifyParams = field(default_factory=ClassifyParams)
    window_mask: WindowMaskParams = field(default_factory=WindowMaskParams)
    display: DisplayParams = field(default_factory=DisplayParams)
    rect_mask: RectMaskParams = field(default_factory=RectMaskParams)

    @classmethod
    def from_yaml(cls, path) -> "Params":
        """从 YAML 文件加载参数(仅覆盖文件中出现的键,其余用默认值)。"""
        if yaml is None:
            raise ImportError("缺少 PyYAML,请先安装: pip install PyYAML")
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return from_mapping(raw)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _nullable_fields(cls) -> set:
    """返回允许为 None 的字段名(注解为 Optional 的字段)。

    本文件有 `from __future__ import annotations`,字段注解是字符串,
    必须用 get_type_hints 解析后才能判 Union[..., None]。
    """
    nullable = set()
    for name, t in get_type_hints(cls).items():
        if get_origin(t) is Union and type(None) in get_args(t):
            nullable.add(name)
    return nullable


def _build(cls, raw: Optional[Dict[str, Any]], section: str = ""):
    """用字典构造数据类。

    严格模式:未知键抛 ValueError(附最近似键名建议,防拼写错误静默回退默认值);
    不可空字段写成 null 同样抛 ValueError(报段名与键名,防 None 直达 numpy)。
    """
    raw = raw or {}
    known = sorted(cls.__dataclass_fields__)
    unknown = [k for k in raw if k not in known]
    if unknown:
        hints = "; ".join(
            "%r → %r?" % (k, get_close_matches(k, known, n=1)) for k in unknown)
        raise ValueError("配置段 %s 含未知键: %s(%s);可用键: %s"
                         % (section, ", ".join(map(repr, unknown)), hints,
                            ", ".join(known)))
    nullable = _nullable_fields(cls)
    for k, v in raw.items():
        if v is None and k not in nullable:
            raise ValueError("配置段 %s 的键 %s 不允许为 null(有默认值,"
                             "请删除或填具体值)" % (section, k))
    return cls(**raw)


_DISPLAY_CLASSES = ("window", "hollow", "seepage", "reject")


def _check_nonneg_int(obj, section: str, names):
    """指定键必须是非负整数(px 类参数)。

    _build 不做类型校验,不查会以三种方式静默出错:负数被 `if x > 0` 当成
    关闭、字符串在深处抛 TypeError、"15" 在切片里被当索引。bool 是 int 的
    子类,故显式排除 True/False(写 true/false 应提示填具体整数)。
    """
    for name in names:
        v = getattr(obj, name)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError("配置段 %s 的键 %s 必须为非负整数,当前为 %r"
                             % (section, name, v))
    return obj


def _check_display(dp: DisplayParams) -> DisplayParams:
    """显示开关只收 0/1,长度下限只收非负整数。

    YAML 里手误的 "ture" 是字符串、同样为真;2 / -1 也会被 bool() 静默当真,
    不查就会静默画错,与 _build 的"防拼写错误静默回退"同一口径。
    """
    for name in _DISPLAY_CLASSES:
        key, v = "show_" + name, getattr(dp, "show_" + name)
        if isinstance(v, bool) or not isinstance(v, int) or v not in (0, 1):
            raise ValueError("配置段 display 的键 %s 必须为 0(不显示)或 "
                             "1(显示),当前为 %r" % (key, v))
    return _check_nonneg_int(
        dp, "display", ["min_len_%s_px" % n for n in _DISPLAY_CLASSES])


def _check_detect(dp: DetectParams) -> DetectParams:
    """检测段的像素类参数校验(边界带宽度不能为负/字符串/布尔)。"""
    return _check_nonneg_int(dp, "detect", ("border_ignore_px",))


def _check_rect_mask(rm: RectMaskParams) -> RectMaskParams:
    """绝对矩形掩膜:enabled 只收 0/1,像素类键只收非负整数。"""
    v = rm.enabled
    if isinstance(v, bool) or not isinstance(v, int) or v not in (0, 1):
        raise ValueError("配置段 rect_mask 的键 enabled 必须为 0(关闭)或 "
                         "1(启用),当前为 %r" % (v,))
    return _check_nonneg_int(rm, "rect_mask",
                             ("morph_close", "min_area_px", "dilate_px",
                              "inpaint_radius"))


def from_mapping(raw: Dict[str, Any]) -> Params:
    return Params(
        preprocess=_build(PreprocessParams, raw.get("preprocess"), "preprocess"),
        detect=_check_detect(_build(DetectParams, raw.get("detect"), "detect")),
        features=_build(FeatureParams, raw.get("features"), "features"),
        classify=_build(ClassifyParams, raw.get("classify"), "classify"),
        window_mask=_build(WindowMaskParams, raw.get("window_mask"), "window_mask"),
        display=_check_display(_build(DisplayParams, raw.get("display"), "display")),
        rect_mask=_check_rect_mask(
            _build(RectMaskParams, raw.get("rect_mask"), "rect_mask")),
    )
