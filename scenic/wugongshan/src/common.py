# -*- coding: utf-8 -*-
"""项目公共配置：路径、日志与基础读写工具。"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

# 项目根目录（src 的上一级）
ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_HTML_DIR = RAW_DIR / "html"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = ROOT / "outputs"
REPORT_DIR = ROOT / "report"

for _d in (CONFIG_DIR, RAW_HTML_DIR, INTERIM_DIR, PROCESSED_DIR, OUTPUT_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SOURCE_CSV = CONFIG_DIR / "sources.csv"
MANIFEST_CSV = RAW_DIR / "manifest.csv"
EXTRACTED_JSONL = INTERIM_DIR / "extracted.jsonl"
DATASET_CSV = PROCESSED_DIR / "wugongshan_guides.csv"
DATASET_JSONL = PROCESSED_DIR / "wugongshan_guides.jsonl"
DATASET_XLSX = PROCESSED_DIR / "武功山景区指南数据集.xlsx"

# 采集与清洗口径（报告与字段说明中引用同一份常量，避免文/数不一致）
SCENIC_AREA = "武功山"
COLLECT_DATE = "2026-10-28"
MIN_OFFICIAL = 1      # 每个景区至少 1 条官方路线
MIN_TRAVELOGUE = 3    # 每个景区至少 3 篇有效游记（任务书要求）


def setup_logging(level: int = logging.INFO) -> None:
    """统一日志格式；Windows 控制台强制 UTF-8，避免中文乱码。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def read_sources() -> list[dict]:
    """读取采集清单（utf-8-sig，兼容 Excel 另存）。"""
    with open(SOURCE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    """写出 UTF-8-SIG CSV，便于 Excel 直接双击打开。"""
    if not rows:
        return
    fieldnames = fieldnames or list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
