import json
import os
import uuid
from pathlib import Path


def _default_session_dir():
    """返回用户可写的会话目录，不依赖 tempfile。

    某些受限 Python 环境（如打包运行时）没有可写的系统临时目录，
    tempfile.gettempdir() 会在导入时直接抛 FileNotFoundError。这里改用
    用户本地应用数据目录；仍可用 P07_SESSION_DIR 覆盖。
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "p07_agent_sessions"
    return Path.home() / ".p07_agent_sessions"


# 用户原话可能包含隐私信息，默认不写进仓库；需要留档时用
# P07_SESSION_DIR 指向受控目录，测试也会覆盖这个变量。
SESSION_DIR = Path(os.environ.get("P07_SESSION_DIR") or _default_session_dir())


class SessionTrace:
    def __init__(self):
        self.events = []

    def record_event(self, event_type, **data):
        """记录可检查的状态摘要，不保存模型内部思维过程。"""
        self.events.append({
            "turn": len(self.events) + 1,
            "event_type": event_type,
            **data
        })

    def call_tool(self, name, function, **arguments):
        """执行工具并记录真实输入、输出或错误。"""
        try:
            result = function(**arguments)
        except Exception as exc:
            self.events.append({
                "turn": len(self.events) + 1,
                "event_type": "tool_call",
                "tool": name,
                "arguments": arguments,
                "observation": {
                    "status": "error",
                    "message": str(exc)
                }
            })
            raise

        self.events.append({
            "turn": len(self.events) + 1,
            "event_type": "tool_call",
            "tool": name,
            "arguments": arguments,
            "observation": {
                "status": "ok",
                "result": result
            }
        })
        return result

    def save(self):
        """将本次工具调用记录保存为 JSONL。"""
        if not self.events:
            raise ValueError("没有工具调用记录，无法保存。")

        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSION_DIR / f"session_{uuid.uuid4().hex}.jsonl"

        with path.open("w", encoding="utf-8") as file:
            for event in self.events:
                file.write(json.dumps(event, ensure_ascii=False) + "\n")

        return path
