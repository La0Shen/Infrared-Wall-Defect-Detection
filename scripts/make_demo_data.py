#!/usr/bin/env python
"""生成演示数据:合成单帧温度图(含空鼓/渗水/窗户),用于无真机时调试管线。

用法:
  python scripts/make_demo_data.py

输出:demo.npy(温度矩阵)+ demo.png(灰度预览)。
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermal_inspect.demo import make_scene  # noqa: E402


def _save_preview(out: Path, name: str, T: np.ndarray) -> None:
    t = np.clip(T, T.min(), T.max())
    t = (t - t.min()) / max(t.max() - t.min(), 1e-6)
    cv2.imwrite(str(out / name), (t * 255).astype(np.uint8))


def main() -> int:
    ap = argparse.ArgumentParser(description="生成演示数据(合成单帧温度图:含空鼓/渗水/窗户)")
    ap.add_argument("--output", default=None,
                    help="输出目录(默认 data/raw/demo)")
    args = ap.parse_args()

    out = Path(args.output) if args.output else HERE.parent / "data" / "raw" / "demo"
    out.mkdir(parents=True, exist_ok=True)

    T = make_scene()
    np.save(str(out / "demo.npy"), T)
    _save_preview(out, "demo.png", T)
    print("已生成单帧演示数据: %s" % out)
    print("可运行: python scripts/run_inspection.py --input %s" % (out / "demo.npy"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
