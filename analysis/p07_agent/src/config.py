"""项目七本地模型配置；通过环境变量覆盖默认值。"""

import os


OLLAMA_URL = os.environ.get("P07_OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("P07_OLLAMA_MODEL", "qwen3:8b")
