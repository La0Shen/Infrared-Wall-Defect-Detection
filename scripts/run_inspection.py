#!/usr/bin/env python
"""CLI 入口:方案一(单帧基线管线)。对应 总体方案.md §2。

用法:
  # 单张温度图(演示 .npy 或真实 R-JPEG)
  python scripts/run_inspection.py --input data/raw/demo/demo.npy
  python scripts/run_inspection.py --input data/raw/楼栋1.JPG
  # 目录:对目录内每张图分别跑方案一并输出
  python scripts/run_inspection.py --input data/raw/某目录

输出分两处(路径可各自用参数改):
  --output       <根>/<图片名>/   结果数据:defects.csv / temperature.npy /
                                  summary.json / mask_NNN_*.png / rect_mask.png
  --output-final <根>/<图片名>/   **标注图**:overlay.png(修复后的净墙)
                                  与 overlay_preinpaint.png(修复前的原画面)
  `--output-final` 默认指向**一个固定目录** `data/output/images`:所有跑过的图都
  归拢在那里,按图片名分文件夹,每个文件夹里就只有那两张图(历次共用,同名会覆盖)。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermal_inspect.config import Params  # noqa: E402
from thermal_inspect.pipeline import run_on_path, save_results  # noqa: E402

SUPPORTED = (".jpg", ".jpeg", ".npy")

OUT_ROOT = HERE.parent / "data" / "output"
# 所有标注图统一落这里(历次共用):<IMAGE_ROOT>/<图片名>/{overlay,overlay_preinpaint}.png
IMAGE_ROOT = OUT_ROOT / "images"


def _collect(input_path):
    """收集输入:单文件 → [path];目录 → 按文件名排序的全部支持文件。"""
    p = Path(input_path)
    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
    else:
        files = [p]
    return [f for f in files if f.suffix.lower() in SUPPORTED]


def build_parser() -> argparse.ArgumentParser:
    """命令行参数(单独成函数,便于用例断言默认值——默认落点是给人看的契约)。"""
    ap = argparse.ArgumentParser(description="外墙热红外缺陷检测:方案一(单帧基线管线)")
    ap.add_argument("--input", required=True,
                    help="输入 R-JPEG(.jpg/.jpeg)/ .npy 温度矩阵;或包含它们的目录"
                         "(目录内每张图独立跑方案一)")
    ap.add_argument("--config", default=str(HERE.parent / "config" / "defaults.yaml"))
    ap.add_argument("--output", default=str(OUT_ROOT / "formal"),
                    help="结果数据根目录:<根>/<图片名>/(默认 %(default)s)")
    ap.add_argument("--output-final", default=str(IMAGE_ROOT),
                    help="标注图根目录:<根>/<图片名>/{overlay,overlay_preinpaint}.png"
                         "(默认 %(default)s;所有跑过的图都归拢在这里)")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    params = Params.from_yaml(args.config)
    files = _collect(args.input)
    if not files:
        print("未找到输入文件(支持 %s): %s" % (" / ".join(SUPPORTED), args.input))
        return 1

    for f in files:
        print("[处理] %s(方案一)" % f.name)
        # 每张图各一份,不能提到循环外——否则目录模式下会串图
        warnings = []
        debug = {}
        T, defects = run_on_path(f, params, warnings, debug)
        out = save_results(args.output, args.output_final, f.stem, T, defects, params, scheme="single",
                           warnings=warnings, debug=debug)
        counts = {}
        for d in defects:
            counts[d.label] = counts.get(d.label, 0) + 1
        print("  温度范围 %.1f~%.1f℃,检出 %d 处: %s" %
              (T.min(), T.max(), len(defects), counts or "无"))
        print("  结果: %s" % out)

    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
