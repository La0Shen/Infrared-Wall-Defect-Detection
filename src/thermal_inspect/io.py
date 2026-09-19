"""R-JPEG / npy 温度图读取。对应 总体方案.md §1.2 ①。

R-JPEG 经 DJI Thermal SDK 解析(按 PyPI 包 dji-thermal-sdk 0.0.2 的真实接口):
需先 dji_init 加载原生 libdirp.dll——pip 包不带 DLL,需从大疆官网下载
DJI Thermal SDK 解压,并用环境变量 DJI_DIRP_DLL 指定 libdirp.dll 完整路径
(未指定时用 SDK 默认相对路径 windows/libdirp.dll)。SDK 输出即摄氏温度,
无需开尔文换算。SDK 未安装 / DLL 缺失 / 非大疆 R-JPEG 时退回灰度读取并
打印强警告,同时向 warnings 参数(可选列表)追加降级记录,供 summary.json
留痕。
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

_SDK_STATE = {"tried": False, "ok": False}  # 进程内缓存 dji_init 结果,避免逐帧重载 DLL


def read_temperature(path, warnings: Optional[list] = None) -> np.ndarray:
    """读取输入,返回温度矩阵(℃,float32)。

    支持:
      - .npy        温度矩阵(演示数据 / 预处理产物)
      - .jpg/.jpeg  R-JPEG:优先经 DJI Thermal SDK 解析;SDK 未安装、DLL 缺失
                    或解析失败时退回灰度读取并打印强警告(灰度值不代表真实
                    温度,仅用于开发调试),同时向 warnings 追加一条降级记录。
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".npy":
        return np.load(str(path)).astype(np.float32)

    if suffix in (".jpg", ".jpeg"):
        try:
            return _read_rjpeg_dji(path)
        except ImportError:
            reason = "未安装 dji_thermal_sdk 包"
        except Exception as exc:  # DLL 缺失 / 非大疆 R-JPEG / 解析失败
            reason = str(exc)
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise FileNotFoundError("无法读取图像: %s" % path)
        print("[warn] 输入降级: %s 退回灰度伪温度(%s)。灰度值不代表真实温度,"
              "缺陷温度特征不可信,仅用于开发调试" % (path.name, reason))
        if warnings is not None:
            warnings.append({"file": path.name, "level": "degraded", "reason": reason,
                             "effect": "灰度伪温度(非真实摄氏温度)"})
        return gray.astype(np.float32)

    raise ValueError("不支持的文件类型: %s(支持 .npy / .jpg / .jpeg)" % suffix)


def _ensure_dji_sdk() -> bool:
    """加载 libdirp.dll 并返回是否成功。

    进程内缓存:同一进程先失败后设置 DJI_DIRP_DLL 不会重试,需重启进程。
    dji_init 内部吞掉 FileNotFoundError 只打印官网链接,故靠 dji_sdk._libdirp
    判空检测加载结果(该私有属性在 0.0.2 源码中存在)。
    """
    if _SDK_STATE["tried"]:
        return _SDK_STATE["ok"]
    _SDK_STATE["tried"] = True
    from dji_thermal_sdk import dji_sdk  # type: ignore
    dji_sdk.dji_init(os.environ.get("DJI_DIRP_DLL"))
    _SDK_STATE["ok"] = bool(dji_sdk._libdirp)
    return _SDK_STATE["ok"]


def _read_rjpeg_dji(path: Path) -> np.ndarray:
    """经 DJI Thermal SDK 读取 R-JPEG 温度矩阵(℃,float32)。

    按 dji-thermal-sdk 0.0.2 真实接口调用:dirp_create_from_rjpeg 接收
    (数据缓冲, 字节数, 二级指针句柄);dirp_measure_ex 输出 float32 摄氏。
    温度缓冲经 np.frombuffer 直取,不落 .raw 临时文件(避开
    utility.rjpeg_to_heatmap 的磁盘副作用与 SDK 全局 DIRP_HANDLE)。
    """
    if not _ensure_dji_sdk():
        raise RuntimeError("libdirp.dll 未加载:请从大疆官网下载 DJI Thermal SDK,"
                           "解压后设置环境变量 DJI_DIRP_DLL 指向 libdirp.dll 完整路径")
    from dji_thermal_sdk import dji_sdk  # type: ignore

    data = path.read_bytes()
    buf = ctypes.create_string_buffer(data, len(data))
    h = ctypes.c_void_p()
    ret = dji_sdk.dirp_create_from_rjpeg(buf, ctypes.c_int32(len(data)), ctypes.byref(h))
    if ret != dji_sdk.DIRP_SUCCESS or not h.value:
        raise RuntimeError("dirp_create_from_rjpeg 失败(ret=%s),可能非 DJI R-JPEG: %s"
                           % (ret, path))
    try:
        res = dji_sdk.dirp_resolution_t()
        ret = dji_sdk.dirp_get_rjpeg_resolution(h, ctypes.byref(res))
        if ret != dji_sdk.DIRP_SUCCESS:
            raise RuntimeError("dirp_get_rjpeg_resolution 失败(ret=%s)" % ret)
        w, hh = int(res.width), int(res.height)
        out = ctypes.create_string_buffer(w * hh * 4)
        ret = dji_sdk.dirp_measure_ex(h, ctypes.byref(out), ctypes.c_int32(w * hh * 4))
        if ret != dji_sdk.DIRP_SUCCESS:
            raise RuntimeError("dirp_measure_ex 失败(ret=%s)" % ret)
        return np.frombuffer(out.raw, dtype=np.float32, count=w * hh).reshape(hh, w).copy()
    finally:
        dji_sdk.dirp_destroy(h)
