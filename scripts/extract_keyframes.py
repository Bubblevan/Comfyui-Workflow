# -*- coding: utf-8 -*-
"""从参考图生视频结果中筛选少量清晰关键帧，放入人工审核区。

设计原则：视频帧默认不进入训练集；只有人工确认身份、服装和肢体都稳定后，
才把文件复制到“审核通过”目录，再纳入人物动作增广集。
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import cv2
import numpy as np


视频后缀 = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def 清晰度分数(图像: np.ndarray) -> float:
    灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)
    清晰度 = float(cv2.Laplacian(灰度, cv2.CV_64F).var())
    亮度 = float(np.mean(灰度))
    亮度惩罚 = 1.0
    if 亮度 < 35 or 亮度 > 225:
        亮度惩罚 = 0.65
    return 清晰度 * 亮度惩罚


def 小图(图像: np.ndarray) -> np.ndarray:
    灰度 = cv2.cvtColor(图像, cv2.COLOR_BGR2GRAY)
    return cv2.resize(灰度, (96, 96), interpolation=cv2.INTER_AREA).astype(np.float32)


def 差异分数(左图: np.ndarray, 右图: np.ndarray) -> float:
    return float(np.mean(np.abs(小图(左图) - 小图(右图))))


def 写入中文路径(图像: np.ndarray, 路径: Path) -> bool:
    """通过编码后写文件，绕过 Windows 下 OpenCV 对中文路径的限制。"""
    成功, 缓冲区 = cv2.imencode(".png", 图像)
    if not 成功:
        return False
    缓冲区.tofile(str(路径))
    return 路径.exists() and 路径.stat().st_size > 0


def 读取候选帧(视频路径: Path, 采样每秒: float) -> tuple[list[tuple[int, float, float, np.ndarray]], float, int, int]:
    捕获 = cv2.VideoCapture(str(视频路径))
    if not 捕获.isOpened():
        return [], 0.0, 0, 0

    帧率 = float(捕获.get(cv2.CAP_PROP_FPS) or 24.0)
    总帧数 = int(捕获.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    宽度 = int(捕获.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    高度 = int(捕获.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    间隔 = max(1, int(round(帧率 / max(0.1, 采样每秒))))
    候选 = []
    帧号 = 0
    while True:
        成功, 图像 = 捕获.read()
        if not 成功:
            break
        if 帧号 % 间隔 == 0:
            候选.append((帧号, 帧号 / 帧率, 清晰度分数(图像), 图像.copy()))
        帧号 += 1
    捕获.release()
    return 候选, 帧率, 宽度, 高度


def 选择关键帧(候选: list[tuple[int, float, float, np.ndarray]], 保留数量: int) -> list[tuple[int, float, float, np.ndarray]]:
    if not 候选:
        return []
    数量 = min(max(1, 保留数量), len(候选))
    # 先按时间分桶，避免五张图都来自动作中的同一瞬间。
    分桶: list[list[tuple[int, float, float, np.ndarray]]] = [[] for _ in range(数量)]
    for 序号, 项 in enumerate(候选):
        分桶[min(数量 - 1, 序号 * 数量 // len(候选))].append(项)

    选择 = []
    for 桶 in 分桶:
        桶.sort(key=lambda 项: 项[2], reverse=True)
        for 项 in 桶:
            if not 选择 or all(差异分数(项[3], 已选[3]) >= 5.0 for 已选 in 选择):
                选择.append(项)
                break
    # 极短视频或相似动作可能导致某个桶没有合格帧，按清晰度补足。
    if len(选择) < 数量:
        for 项 in sorted(候选, key=lambda 项: 项[2], reverse=True):
            if 项 in 选择:
                continue
            if all(差异分数(项[3], 已选[3]) >= 3.0 for 已选 in 选择):
                选择.append(项)
            if len(选择) == 数量:
                break
    return sorted(选择[:数量], key=lambda 项: 项[0])


def 主程序() -> None:
    根目录 = Path(__file__).resolve().parents[1]
    参数 = argparse.ArgumentParser(description="筛选参考图生视频结果中的清晰关键帧")
    参数.add_argument("--视频目录", type=Path, default=根目录 / "视频扩充数据" / "原视频")
    参数.add_argument("--输出目录", type=Path, default=根目录 / "视频扩充数据" / "待审核关键帧")
    参数.add_argument("--每秒候选数", type=float, default=3.0)
    参数.add_argument("--每段保留数", type=int, default=5)
    参数.add_argument("--角色", type=str, default="未分类")
    参数.add_argument("--最小清晰度", type=float, default=35.0)
    选项 = 参数.parse_args()

    视频文件 = sorted(p for p in 选项.视频目录.rglob("*") if p.is_file() and p.suffix.lower() in 视频后缀)
    输出目录 = 选项.输出目录 / 选项.角色
    输出目录.mkdir(parents=True, exist_ok=True)
    清单路径 = 输出目录 / "关键帧审核清单.csv"
    清单 = []

    for 视频 in 视频文件:
        候选, 帧率, 宽度, 高度 = 读取候选帧(视频, 选项.每秒候选数)
        关键帧 = [项 for 项 in 选择关键帧(候选, 选项.每段保留数) if 项[2] >= 选项.最小清晰度]
        for 输出序号, (帧号, 时间秒, 分数, 图像) in enumerate(关键帧, 1):
            文件名 = f"{视频.stem}_关键帧_{输出序号:02d}.png"
            输出路径 = 输出目录 / 文件名
            if not 写入中文路径(图像, 输出路径):
                continue
            清单.append({
                "角色": 选项.角色,
                "视频文件": 视频.name,
                "关键帧文件": 文件名,
                "帧序号": 帧号,
                "时间秒": f"{时间秒:.3f}",
                "清晰度分数": f"{分数:.2f}",
                "宽度": 宽度,
                "高度": 高度,
                "状态": "待人工审核",
            })
        print(f"{视频.name}: 候选 {len(候选)}，入审核区 {len(关键帧)}")

    with 清单路径.open("w", encoding="utf-8-sig", newline="") as 文件:
        字段 = ["角色", "视频文件", "关键帧文件", "帧序号", "时间秒", "清晰度分数", "宽度", "高度", "状态"]
        写入器 = csv.DictWriter(文件, fieldnames=字段)
        写入器.writeheader()
        写入器.writerows(清单)
    print(f"共生成 {len(清单)} 张待审核关键帧：{清单路径}")


if __name__ == "__main__":
    主程序()
