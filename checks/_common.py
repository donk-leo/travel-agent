# -*- coding: utf-8 -*-
"""检查脚本共用工具：统一报告格式、JSONL 校验、未产出时的友好退出。"""
from __future__ import annotations

import json
import sys
import pathlib
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.io_utils import read_jsonl  # noqa: E402


class Report:
    """收集错误/警告并统一输出；errors 非空则退出码为 1。"""

    def __init__(self, title: str) -> None:
        self.title = title
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.info: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)

    def note(self, msg: str) -> None:
        self.info.append(msg)

    def finish(self) -> int:
        print(f"\n=== {self.title} —— {'通过' if not self.errors else '不通过'} ===")
        for line in self.info:
            print(f"  {line}")
        for line in self.warns:
            print(f"  [警告] {line}")
        for line in self.errors:
            print(f"  [错误] {line}")
        print("\n" + ("检查通过，可用于交接。" if not self.errors
                      else "存在问题，请按 [错误] 修正后再交接。"))
        return 1 if self.errors else 0


def not_ready(project: str, paths: Iterable[pathlib.Path]) -> int:
    """产出尚未生成：不算失败（项目还没开始做）。"""
    print(f"\n=== {project} —— 尚未产出 ===")
    for p in paths:
        print(f"  缺失：{p}")
    print("  项目未开始时属正常；开始后请按 standards/handover 的产出清单生成文件。")
    return 0


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return list(read_jsonl(path))


def check_fields(rep: Report, records: list[dict], required: Iterable[str],
                 enums: dict[str, set[str]] | None = None,
                 label: str = "记录") -> None:
    """必填字段 + 枚举值校验。"""
    enums = enums or {}
    required = list(required)
    for i, row in enumerate(records, start=1):
        for field in required:
            if str(row.get(field, "")).strip() == "":
                rep.error(f"第 {i} 条{label}缺少字段 {field}")
        for field, allowed in enums.items():
            value = row.get(field)
            if value is not None and str(value) not in allowed:
                rep.error(f"第 {i} 条{label}的 {field} 非法：{value}（允许 {sorted(allowed)}）")


def check_int_range(rep: Report, records: list[dict], start_field: str,
                    end_field: str, label: str = "span") -> None:
    for i, row in enumerate(records, start=1):
        try:
            start, end = int(row[start_field]), int(row[end_field])
        except (KeyError, TypeError, ValueError):
            rep.error(f"第 {i} 条{label}不是整数：{row.get(start_field)} / {row.get(end_field)}")
            continue
        if start < 0 or end <= start:
            rep.error(f"第 {i} 条{label}区间非法：{start}..{end}")


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "standards" / f"schema_{name}.json").read_text(encoding="utf-8"))
