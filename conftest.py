"""pytest 公共配置:把 src 加入 sys.path,使测试可直接导入源码包。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
