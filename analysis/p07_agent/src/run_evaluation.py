"""运行项目七真实模型交付案例，保存原始结果和会话轨迹。"""

import contextlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent import run_agent
from config import MODEL, OLLAMA_URL


OUTPUT = Path(__file__).resolve().parents[1] / "outputs" / "evaluation_results.json"

# 以下为人工设计的测试请求，不是采集语料。
CASES = [
    ("family_elder_one_day", "亲子与老人一日游", "我想带孩子和老人去长隆玩一天，喜欢游乐项目，尽量少走路。"),
    ("friends_one_day", "朋友白云山一日游", "我和朋友去广州白云山玩一天，喜欢自然风景和拍照，希望少爬坡。"),
    ("couple_two_days", "伴侣武功山两日游", "我和伴侣去武功山玩两天，想看日出、欣赏自然风景，预算有限，希望行程不要太累。"),
    ("missing_information", "缺少景区与天数", "我想和父母出去玩，希望行程轻松一点。"),
    ("followup_combined", "追问后补充", "我想和父母出去玩，希望行程轻松一点。\n广州白云山，一天。"),
    ("conflicting_constraints", "冲突需求", "我想一天游遍武功山的所有景点，但不能步行，也不能乘坐任何交通工具。"),
    ("no_match", "图谱无匹配（人工虚构的名称）", "广州白云山有没有叫火星大峡谷的景点？"),
    ("list_pois", "查询白云山地点", "广州白云山有哪些景点？"),
]


def main():
    records = []
    for case_id, label, query in CASES:
        started = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_agent(query)
        route = result.get("route") or {}
        validation = route.get("validation") or {}
        proposal = route.get("proposal") or {}
        records.append({
            "case_id": case_id,
            "label": label,
            "query": query,
            "status": result["status"],
            "message": result["message"],
            "error": result["error"],
            "intent": result["intent"],
            "decision": result["decision"],
            "tool_decisions": result["tool_decisions"],
            "route_valid": validation.get("valid"),
            "route_nodes": proposal.get("node_ids", []),
            "route_segments": validation.get("segments", []),
            "route_uncertainties": proposal.get("uncertainties", []),
            "suggestions": result["suggestions"],
            "poi_results": result["poi_results"],
            "trace_file": result["trace_file"],
            "seconds": round(time.monotonic() - started, 1),
        })
        print(f'{label}：{result["status"]}；记录 {result["trace_file"]}', flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "ollama_url": OLLAMA_URL,
        "cases": records
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = sum(record["status"] == "error" or not record["trace_file"] for record in records)
    print(f"结果：{OUTPUT}；执行错误或记录缺失：{failures}。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
