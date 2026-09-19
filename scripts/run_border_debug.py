#!/usr/bin/env python
"""边框填充插件的**独立调试入口**(本项目新增,不改任何既有文件)。

做法:先读原始温度 → 用 `border_fill.apply` 改图(把最外 `width_px` 一圈当墙体、
整圈改成背景色)→ 再交给**原样的** `pipeline.run_single` 走完整方案一。既有入口
`scripts/run_inspection.py` 一行未动,不加 `--fill-*` 时它的输出与加本插件之前
逐字节一致。

用法:
  # 两种背景色各跑一次,并自动与"关闭"基准对照(推荐:一次看全)
  python scripts/run_border_debug.py --input data/raw/test01.JPG --compare

  # 只跑一种,自己指定宽度
  python scripts/run_border_debug.py --input data/raw/test01.JPG --fill-median 1 --width-px 20
  python scripts/run_border_debug.py --input data/raw/test01.JPG --fill-ns 1

两个开关是**互斥**的,同时给 1 会直接报错(它们填的是同一条带,同时开只会互相覆盖)。
输出分别落在 `--output/<名字>_baseline` 与 `--output/<名字>_<模式>`,可直接比
`overlay.png`、`defects.csv`、`summary.json`。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermal_inspect.border_fill import BorderFillParams, apply as border_apply  # noqa: E402
from thermal_inspect.config import Params  # noqa: E402
from thermal_inspect.io import read_temperature  # noqa: E402
from thermal_inspect.pipeline import run_single, save_results  # noqa: E402

SUPPORTED = (".jpg", ".jpeg", ".npy")


def _collect(input_path):
    p = Path(input_path)
    files = (sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
             if p.is_dir() else [p])
    return [f for f in files if f.suffix.lower() in SUPPORTED]


def _run_one(path, params, bf, out_root, out_final, tag, out_name=None):
    """读原始温度 → 边框填充 → 原样的 run_single → 存盘。返回 (名字, 缺陷数, 计数)。"""
    warnings = []
    T_raw = read_temperature(path, warnings=warnings)
    T_raw = border_apply(T_raw, bf)
    T, defects = run_single(T_raw, params)
    name = out_name or ("%s_%s" % (path.stem, tag))
    out = save_results(out_root, out_final, name, T, defects, params, scheme="single",
                       warnings=warnings)
    counts = {}
    for d in defects:
        counts[d.label] = counts.get(d.label, 0) + 1
    return name, len(defects), counts, out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="边框填充调试插件:把画面最外一圈当墙体、整圈改成背景色")
    ap.add_argument("--input", required=True,
                    help="输入 R-JPEG(.jpg/.jpeg)/ .npy 温度矩阵;或包含它们的目录")
    ap.add_argument("--config", default=str(HERE.parent / "config" / "defaults.yaml"),
                    help="既有管线参数(默认 config/defaults.yaml,本插件不改它)")
    ap.add_argument("--output", default=str(HERE.parent / "data" / "output" / "border_debug"))
    ap.add_argument("--output-final", default=str(HERE.parent / "data" / "output" / "border_debug" / "final"))
    ap.add_argument("--fill-median", type=int, default=0,
                    help="1=边框整圈平铺成全图中位数(一个常数)")
    ap.add_argument("--fill-ns", type=int, default=0,
                    help="1=边框交给原方案 NS 修复,从内侧墙面往里延伸(逐像素)")
    ap.add_argument("--width-px", type=int, default=20,
                    help="边框宽度:画面最外沿**向内** N px(默认 20)")
    ap.add_argument("--inpaint-radius", type=int, default=3,
                    help="NS 修复半径(px),默认 3;仅 --fill-ns 1 时起作用")
    ap.add_argument("--compare", action="store_true",
                    help="对每张图依次跑 关闭 / 中位数 / NS 三种,并打印对照表")
    args = ap.parse_args()

    params = Params.from_yaml(args.config)
    files = _collect(args.input)
    if not files:
        print("未找到输入文件(支持 %s): %s" % (" / ".join(SUPPORTED), args.input))
        return 1

    if args.compare:
        # 三种模式一次跑全,方便直接判断效果
        modes = [("baseline", BorderFillParams(fill_median=0, fill_ns=0,
                                               width_px=args.width_px,
                                               inpaint_radius=args.inpaint_radius)),
                 ("median", BorderFillParams(fill_median=1,
                                             width_px=args.width_px,
                                             inpaint_radius=args.inpaint_radius)),
                 ("ns", BorderFillParams(fill_ns=1, width_px=args.width_px,
                                         inpaint_radius=args.inpaint_radius))]
    else:
        modes = [("median" if args.fill_median else
                  ("ns" if args.fill_ns else "baseline"),
                  BorderFillParams(fill_median=args.fill_median, fill_ns=args.fill_ns,
                                   width_px=args.width_px,
                                   inpaint_radius=args.inpaint_radius))]

    for f in files:
        print("[处理] %s  (width_px=%d, inpaint_radius=%d)"
              % (f.name, args.width_px, args.inpaint_radius))
        rows = []
        for tag, bf in modes:
            # 互斥开关与非法取值在这里挡下来,报错不静默
            try:
                name, n, counts, out = _run_one(f, params, bf, args.output, args.output_final, tag)
            except ValueError as e:
                print("  配置有误: %s" % e)
                return 2
            rows.append((tag, n, counts, out))
            print("  [%-8s] 检出 %3d 处: %s" % (tag, n, counts or "无"))
        if len(rows) > 1:
            base = rows[0][1]
            print("  对照(以 baseline 为基准):")
            for tag, n, _, _ in rows[1:]:
                print("    %-8s %+d 处 (%d → %d)" % (tag, n - base, base, n))
        for tag, _, _, out in rows:
            print("    %-8s → %s" % (tag, out))

    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
