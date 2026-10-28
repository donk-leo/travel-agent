# -*- coding: utf-8 -*-
"""全仓库路径常量。所有脚本只从这里取路径，禁止自己拼相对路径。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENIC = ROOT / "scenic"
ANALYSIS = ROOT / "analysis"
STANDARDS = ROOT / "standards"
CHECKS = ROOT / "checks"
DOCS = ROOT / "docs"
REPORT = ROOT / "report"
ARCHIVE = ROOT / "archive"

#: 三个景区（与 doc_id 前缀、data/processed 文件名一一对应）
SCENIC_AREAS = ("changlong", "baiyunshan", "wugongshan")

#: 项目目录名 -> 交接卡
PROJECTS = {
    "p02_entities": "p02_entities",
    "p03_routes": "p03_routes",
    "p04_coref": "p04_coref",
    "p05_conditions": "p05_conditions",
    "p06_graph": "p06_graph",
    "p07_agent": "p07_agent",
}


def scenic_dir(area: str) -> Path:
    """景区数据目录。"""
    if area not in SCENIC_AREAS:
        raise ValueError(f"未知景区：{area}（可选 {SCENIC_AREAS}）")
    return SCENIC / area


def scenic_csv(area: str) -> Path:
    """项目 1 主数据集路径。"""
    return scenic_dir(area) / "data" / "processed" / f"{area}_guides.csv"


def analysis_dir(project: str) -> Path:
    return ANALYSIS / project


def outputs(project: str) -> Path:
    return analysis_dir(project) / "outputs"


def handover(project: str) -> Path:
    return STANDARDS / "handover" / f"{project.split('_')[0]}_{project.split('_', 1)[1]}.yaml"


def schema(name: str) -> Path:
    return STANDARDS / f"schema_{name}.json"
