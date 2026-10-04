#!/usr/bin/env python
"""CLI 入口:**通用红外图片**(非大疆)的缺陷检测(本项目新增)。

**本脚本是新文件**:`scripts/run_inspection.py`(大疆入口)与整条管线**一行未改**。
接线方式沿用 `run_border_debug.py` 那套插件做法:

    T = ir_reader.read_ir(图片, 标定参数)      ← 本项目新增的读取器(翻译成 ℃)
    T, defects = run_single(T, params)          ← 原样的管线,一行没动
    save_results(...)                           ← 原样的输出

用法:
  # 伪彩热图:必须给量程(图里"最冷/最热色阶"对应多少℃)
  python scripts/run_ir.py --input 某图.jpg --mode palette --colormap iron --t-min 10 --t-max 40

  # 灰度热图:同样要给量程
  python scripts/run_ir.py --input 某图.png --mode gray --t-min 0 --t-max 60

  # 已经是温度矩阵(.npy / 16bit TIFF 存的温度值)
  python scripts/run_ir.py --input 某矩阵.npy --mode matrix

  # 用色标条自采色表(比猜厂家色表准)
  python scripts/run_ir.py --input 某图.jpg --mode palette --colormap custom \
         --palette-file 色标条.png --t-min 10 --t-max 40

⚠ **量程是这张图能不能用的关键**:同一个颜色,量程 10~40℃ 时是 25℃,
量程 20~120℃ 时是 70℃。而且很多消费级热像仪默认开 AGC(自动伸缩量程),
那种图的量程根本没记录在文件里——能用固定量程拍就一定要固定。

⚠ 读进来的温度是"近似温度":形状判据与 z 分数判据照常有效,但**以℃为单位的
阈值(空鼓 1.5℃ 等)需要按本设备重新标定**,否则结论只可用于相对比较。
详见 src/thermal_inspect/ir_reader.py 的模块说明。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermal_inspect.config import Params  # noqa: E402
from thermal_inspect.ir_reader import IrCalibParams, read_ir  # noqa: E402
from thermal_inspect.pipeline import run_single, save_results  # noqa: E402

SUPPORTED = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".npy")
OUT_ROOT = HERE.parent / "data" / "output"
IMAGE_ROOT = OUT_ROOT / "images"     # 与大疆入口共用同一个图片根(所有图归拢在这里)


def _collect(input_path):
    p = Path(input_path)
    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
    else:
        files = [p]
    return [f for f in files if f.suffix.lower() in SUPPORTED]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="通用红外图片(非大疆)缺陷检测:读取器翻译成 ℃,再走原样的方案一管线")
    ap.add_argument("--input", required=True, help="红外图片 / 温度矩阵;或包含它们的目录")
    ap.add_argument("--mode", default="palette", choices=("gray", "palette", "matrix"),
                    help="读取模式(默认 palette:伪彩热图)")
    ap.add_argument("--t-min", type=float, default=10.0, help="量程下限 ℃(默认 10)")
    ap.add_argument("--t-max", type=float, default=40.0, help="量程上限 ℃(默认 40)")
    ap.add_argument("--colormap", default="iron",
                    help="色表名:iron/jet/rainbow/inferno/turbo/hot/gray,或 custom")
    ap.add_argument("--palette-file", default=None,
                    help="colormap=custom 时的色标条图片路径")
    ap.add_argument("--invert", action="store_true", help="色阶方向反了时打开")
    ap.add_argument("--invert-gray", action="store_true", help="gray 模式:0 表示最热")
    ap.add_argument("--config", default=str(HERE.parent / "config" / "defaults.yaml"))
    ap.add_argument("--output", default=str(OUT_ROOT / "ir"),
                    help="结果数据根目录:<根>/<图片名>/(默认 %(default)s)")
    ap.add_argument("--output-final", default=str(IMAGE_ROOT),
                    help="标注图根目录:<根>/<图片名>/(默认 %(default)s)")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    calib = IrCalibParams(mode=args.mode, t_min=args.t_min, t_max=args.t_max,
                          colormap=args.colormap, palette_file=args.palette_file,
                          invert=args.invert, invert_gray=args.invert_gray)
    params = Params.from_yaml(args.config)      # 与大疆入口共用同一份检测参数

    files = _collect(args.input)
    if not files:
        print("未找到输入文件(支持 %s): %s" % (" / ".join(SUPPORTED), args.input))
        return 1

    print("[标定] mode=%s 量程=%.1f~%.1f℃%s"
          % (calib.mode, calib.t_min, calib.t_max,
             "" if calib.mode != "palette" else " colormap=%s" % calib.colormap))
    for f in files:
        warnings = []
        debug = {}
        try:
            T = read_ir(f, calib, warnings)
        except (FileNotFoundError, ValueError) as exc:
            print("[跳过] %s: %s" % (f.name, exc))
            continue
        T, defects = run_single(T, params, debug=debug)
        out = save_results(args.output, args.output_final, f.stem, T, defects, params,
                           scheme="generic_ir", warnings=warnings, debug=debug)
        counts = {}
        for d in defects:
            counts[d.label] = counts.get(d.label, 0) + 1
        print("  温度范围 %.1f~%.1f℃,检出 %d 处: %s"
              % (T.min(), T.max(), len(defects), counts or "无"))
        print("  结果: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
