# -*- coding: utf-8 -*-
"""T1.5 临时兼容层：把 P5 的 `cond_id` 固定到「旧条件原 ID」上。

背景（根因见 `docs/optimization/GRAPH_RERUN_REPORT.md` §P5 cond_id 稳定性）：
`analysis/p05_conditions/src/extract_conditions.py` 第 503–507 行先按
`(scenic_area, doc_id, char_start, suggestion_start, suggestion_text)` 排序，
再 `enumerate` 顺序分配 `CND-%04d`。T1.5 新增的 `WGS-O-07/08` 在 doc_id 序上
落在 `WGS-O-06` 与 `WGS-T-02` 之间，导致新条件占用 CND-0016/0017、旧
CND-0016..0036 整体 +2 重编号，`manual_review_gold.csv` 的 20 条人工标注
（按旧 cond_id 挂）会错配。

本脚本只做一件事：**只改 cond_id 与行序，不改任何字段值**，把旧 36 条条件
恢复为 `1c2a578` 的原 cond_id，新条件从 `max(旧 id)+1` 追加。它是 D2 阶段的
临时措施，不是 P5 契约变更；P5 owner 修好 src 后应删除本层。

用法（仓库根目录）：
    # 1) 初始化映射（只跑一次；输入 = git show 1c2a578:.../conditions.jsonl 落盘文件）
    python analysis/p05_conditions/outputs/apply_stable_ids.py --init-map <legacy_conditions.jsonl>

    # 2) 每次 extract_conditions.py 之后执行：稳定 ID + 重写 conditions.jsonl
    python analysis/p05_conditions/outputs/apply_stable_ids.py --write

    # 3) 校验（不写盘）
    python analysis/p05_conditions/outputs/apply_stable_ids.py --check

确定性：纯标准库、无网络、无时间戳、无随机数；同一输入 + 同一 map 必得同一字节输出，
第二遍 `--write` 不改变 `cond_id_map.json` 的 sha256。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
JSONL = OUT / "conditions.jsonl"
MAP = OUT / "cond_id_map.json"
SIG_SEP = "\u0001"
SCHEMA = "t1.5-cond-id-map-v1"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def signature(row: dict) -> str:
    """旧/新条件的稳定签名：doc_id + 条件 + 建议 + 两个字符位置。"""
    return SIG_SEP.join(
        str(row[k]) for k in ("doc_id", "condition_text", "suggestion_text", "char_start", "char_end")
    )


def id_num(cond_id: str) -> int:
    return int(cond_id.split("-")[1])


def entry(row: dict, cond_id: str, origin: str) -> dict:
    return {
        "cond_id": cond_id,
        "origin": origin,
        "signature": signature(row),
        "doc_id": row["doc_id"],
        "condition_text": row["condition_text"],
        "suggestion_text": row["suggestion_text"],
    }


def sorted_entries(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: id_num(e["cond_id"]))


def write_map(entries: list[dict], legacy_count: int) -> None:
    payload = {
        "schema": SCHEMA,
        "note": "T1.5 临时兼容层：旧条件保持 1c2a578 的 cond_id；新条件从 max(旧)+1 追加。只改 ID/行序，不改字段值。",
        "signature_fields": ["doc_id", "condition_text", "suggestion_text", "char_start", "char_end"],
        "signature_separator": "\\u0001",
        "legacy_count": legacy_count,
        "entries": sorted_entries(entries),
    }
    MAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_map() -> dict:
    if not MAP.exists():
        raise SystemExit(f"[FAIL] 缺少映射文件 {MAP}，先跑 --init-map")
    payload = json.loads(MAP.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise SystemExit(f"[FAIL] 映射 schema 不符：{payload.get('schema')!r}")
    return payload


def cmd_init_map(legacy_path: Path) -> int:
    legacy = load_jsonl(legacy_path)
    if MAP.exists():
        raise SystemExit(f"[FAIL] {MAP.name} 已存在，--init-map 只允许初始化一次")
    entries = [entry(r, r["cond_id"], "legacy") for r in legacy]
    if len({e["signature"] for e in entries}) != len(entries):
        raise SystemExit("[FAIL] 旧条件签名有重复，无法建立唯一映射")
    write_map(entries, len(entries))
    print(f"[OK] wrote {MAP.name}: legacy={len(entries)}  max={max(id_num(e['cond_id']) for e in entries)}")
    return 0


def cmd_write() -> int:
    payload = load_map()
    entries: list[dict] = payload["entries"]
    legacy_count = int(payload["legacy_count"])
    sig2id = {e["signature"]: e["cond_id"] for e in entries}
    if len(sig2id) != len(entries):
        raise SystemExit("[FAIL] 映射里签名重复")

    rows = load_jsonl(JSONL)
    sigs = [signature(r) for r in rows]
    if len(set(sigs)) != len(sigs):
        raise SystemExit("[FAIL] conditions.jsonl 内有重复签名，拒绝自动映射（需人工确认）")

    # 旧条件必须还在：少一条就说明上游丢了数据
    missing = [e["cond_id"] for e in entries if e["signature"] not in set(sigs)]
    if missing:
        raise SystemExit(f"[FAIL] 映射中的 {len(missing)} 条旧条件在新抽取结果中找不到：{missing[:10]}")

    max_id = max((id_num(e["cond_id"]) for e in entries), default=0)
    new_rows = [r for r in rows if signature(r) not in sig2id]
    new_rows.sort(key=lambda r: (r["scenic_area"], r["doc_id"], r["char_start"],
                                 r["suggestion_start"], r["suggestion_text"]))
    new_ids = []
    for row in new_rows:
        max_id += 1
        cond_id = f"CND-{max_id:04d}"
        sig2id[signature(row)] = cond_id
        entries.append(entry(row, cond_id, "new"))
        new_ids.append(cond_id)

    field_order = list(rows[0].keys())
    for row in rows:
        row["cond_id"] = sig2id[signature(row)]
    rows.sort(key=lambda r: id_num(r["cond_id"]))
    JSONL.write_text(
        "".join(json.dumps({k: row[k] for k in field_order}, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    write_map(entries, legacy_count)
    print(f"[OK] {JSONL.name}: rows={len(rows)} legacy={legacy_count} "
          f"new={len(new_ids)} max_id={max(id_num(r['cond_id']) for r in rows)}")
    if new_ids:
        print("     new cond_id:", ", ".join(new_ids))
    return 0


def cmd_check() -> int:
    payload = load_map()
    entries: list[dict] = payload["entries"]
    legacy_count = int(payload["legacy_count"])
    errors: list[str] = []

    ids = [e["cond_id"] for e in entries]
    if len(ids) != len(set(ids)):
        errors.append("映射里 cond_id 有重复")
    sigs = [e["signature"] for e in entries]
    if len(sigs) != len(set(sigs)):
        errors.append("映射里签名有重复")
    legacy = [e for e in entries if e["origin"] == "legacy"]
    if len(legacy) != legacy_count:
        errors.append(f"legacy 条目 {len(legacy)} ≠ legacy_count {legacy_count}")
    if ids and set(ids) != {f"CND-{i:04d}" for i in range(1, len(ids) + 1)}:
        errors.append("映射 cond_id 不是 1..N 连续编号")
    if [e["cond_id"] for e in entries] != [x["cond_id"] for x in sorted_entries(entries)]:
        errors.append("映射 entries 未按 cond_id 升序排列")

    rows = load_jsonl(JSONL)
    row_ids = [r["cond_id"] for r in rows]
    if len(row_ids) != len(set(row_ids)):
        errors.append(f"conditions.jsonl 里 cond_id 有重复：{len(row_ids) - len(set(row_ids))}")
    sig2id = {e["signature"]: e["cond_id"] for e in entries}
    row_sigs = [signature(r) for r in rows]
    for r, sig in zip(rows, row_sigs):
        if sig not in sig2id:
            errors.append(f"{r['cond_id']} 的签名不在映射里")
        elif sig2id[sig] != r["cond_id"]:
            errors.append(f"{r['cond_id']} 与映射 ID {sig2id[sig]} 不一致")
    missing = [e["cond_id"] for e in legacy if e["signature"] not in set(row_sigs)]
    if missing:
        errors.append(f"旧条件在新文件中找不到：{missing[:10]}")
    if set(row_ids) != set(ids):
        errors.append(f"conditions.jsonl 的 ID 集合 ≠ 映射 ID 集合（{len(set(row_ids) ^ set(ids))} 个差异）")
    if [id_num(c) for c in row_ids] != sorted(id_num(c) for c in row_ids):
        errors.append("conditions.jsonl 未按 cond_id 升序写出")

    print(f"map: entries={len(entries)} legacy={legacy_count} new={len(entries) - legacy_count} "
          f"max={max((id_num(c) for c in ids), default=0)}")
    print(f"conditions.jsonl: rows={len(rows)} unique_ids={len(set(row_ids))}")
    if errors:
        print(f"[FAIL] {len(errors)} 项：", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 1
    print("[OK] 旧条件 ID 稳定、新条件已追加、ID 唯一且连续")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="P5 稳定 cond_id 兼容层（D2 临时措施）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init-map", type=Path, metavar="LEGACY_JSONL", help="从旧 conditions.jsonl 初始化映射")
    g.add_argument("--write", action="store_true", help="按映射重写 conditions.jsonl（幂等）")
    g.add_argument("--check", action="store_true", help="只校验，不写盘")
    args = ap.parse_args()
    if args.init_map:
        return cmd_init_map(args.init_map)
    if args.write:
        return cmd_write()
    return cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
