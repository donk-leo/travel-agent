import json
import os
import uuid
from pathlib import Path


def _is_writable(directory):
    """尝试创建目录并写一个探针文件；受限环境可能只允许工作区写入。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write_test_{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _default_session_dir():
    """返回实际可写的会话目录，不依赖 tempfile。

    某些受限 Python 环境（如打包运行时）没有可写的系统临时目录、用户
    AppData 或家目录，只有项目工作区可写。这里按“仓库同级目录 → 当前
    工作目录 → 用户本地应用数据 → 家目录”的顺序探测，避免导入或保存时
    因 PermissionError 让整个网页请求显示“处理失败”。
    """
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root.parent / "p7_agent_sessions",
        Path.cwd() / "p7_agent_sessions",
    ]
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        candidates.append(Path(base) / "p07_agent_sessions")
    candidates.append(Path.home() / ".p07_agent_sessions")

    for candidate in candidates:
        if _is_writable(candidate):
            return candidate
    return candidates[0]


def _select_session_dir():
    configured = os.environ.get("P07_SESSION_DIR")
    if configured:
        path = Path(configured)
        if _is_writable(path):
            return path
    return _default_session_dir()


# 用户原话可能包含隐私信息，默认不写进仓库；需要留档时用
# P07_SESSION_DIR 指向受控目录。环境不可写时自动退回实际可写目录，
# 不让会话记录失败影响行程结果。
SESSION_DIR = _select_session_dir()


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
