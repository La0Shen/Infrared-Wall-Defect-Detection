"""输出落盘布局测试:标注图归拢在一个固定根目录,按图片名分文件夹,里面只有那两张图。

用户要求的组织:
    <图片根>/<图片名>/{overlay.png, overlay_preinpaint.png}
主结果(defects.csv / temperature.npy / summary.json / mask_NNN_*.png)不搬,
仍在 <结果根>/<图片名>/ 下。
"""
import importlib.util
import os
from pathlib import Path

from thermal_inspect.config import Params
from thermal_inspect.demo import make_scene
from thermal_inspect.pipeline import run_single, save_results

ROOT = Path(__file__).resolve().parents[1]


def _load_cli():
    """把 scripts/run_inspection.py 按路径导入(scripts 不是包,故用 importlib)。"""
    spec = importlib.util.spec_from_file_location(
        "run_inspection_cli", ROOT / "scripts" / "run_inspection.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_image_root_holds_exactly_the_two_images(tmp_path):
    """一个图片文件夹里**只有**那两张图(不多不少)。"""
    p = Params()
    T, defects = run_single(make_scene(), p, debug={})
    img_root = tmp_path / "images"
    save_results(tmp_path / "res", img_root, "case", T, defects, p,
                 scheme="single", debug={"T_preinpaint": T})

    d = img_root / "case"
    assert d.is_dir()
    assert sorted(os.listdir(d)) == ["overlay.png", "overlay_preinpaint.png"], \
        "图片文件夹里应当只有这两张图"


def test_one_subfolder_per_input_image(tmp_path):
    """多张输入图 → 各一个子文件夹,互不混。"""
    p = Params()
    T, defects = run_single(make_scene(), p, debug={})
    img_root = tmp_path / "images"
    for name in ("楼栋1", "楼栋2"):
        save_results(tmp_path / "res", img_root, name, T, defects, p,
                     scheme="single", debug={"T_preinpaint": T})
    assert sorted(os.listdir(img_root)) == ["楼栋1", "楼栋2"]
    for name in ("楼栋1", "楼栋2"):
        assert sorted(os.listdir(img_root / name)) == ["overlay.png", "overlay_preinpaint.png"]


def test_main_results_stay_out_of_the_image_folder(tmp_path):
    """主结果不搬进图片文件夹:两边各自的文件清单不交叉。"""
    p = Params()
    T, defects = run_single(make_scene(), p, debug={})
    res_root, img_root = tmp_path / "res", tmp_path / "images"
    save_results(res_root, img_root, "case", T, defects, p,
                 scheme="single", debug={"T_preinpaint": T})
    res_files = set(os.listdir(res_root / "case"))
    assert {"defects.csv", "temperature.npy", "summary.json"} <= res_files
    assert "overlay.png" not in res_files, "图不该出现在结果数据目录里"
    assert not (img_root / "case" / "defects.csv").exists(), "数据不该出现在图片目录里"


def test_cli_defaults_point_at_one_shared_image_root():
    """CLI 默认:图片落在**固定**的 data/output/images,与 --output 无关。"""
    cli = _load_cli()
    assert cli.IMAGE_ROOT == ROOT / "data" / "output" / "images"
    ap = cli.build_parser()
    d = vars(ap.parse_args(["--input", "x.JPG"]))
    assert Path(d["output_final"]) == cli.IMAGE_ROOT, "图片根目录是固定落点"
    assert Path(d["output"]) == ROOT / "data" / "output" / "formal"
    assert "images" in ap.format_help(), "帮助里要能看出图落到哪儿"


def test_cli_paths_can_still_be_overridden(tmp_path):
    """两个路径都仍可显式指定(调试/对照时用)。"""
    cli = _load_cli()
    ap = cli.build_parser()
    d = vars(ap.parse_args(["--input", "x.JPG",
                            "--output", str(tmp_path / "r"),
                            "--output-final", str(tmp_path / "i")]))
    assert d["output"] == str(tmp_path / "r")
    assert d["output_final"] == str(tmp_path / "i")
