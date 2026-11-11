"""项目七本地模型配置；通过环境变量覆盖默认值。"""

import os


OLLAMA_URL = os.environ.get("P07_OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("P07_OLLAMA_MODEL", "qwen3:8b")
# 本地 8B 模型在 CPU/单卡上生成 JSON 较慢；限制输出长度，避免一次请求
# 因为模型自由发挥而拖到超时。路线/分天仍能放进 1200 个 token。
MAX_TOKENS = int(os.environ.get("P07_MAX_TOKENS", "1200"))
# 路线 JSON 包含节点、分天和说明，需要比普通意图/理由调用更长的输出预算。
ROUTE_MAX_TOKENS = int(os.environ.get("P07_ROUTE_MAX_TOKENS", "1800"))
# 路线 prompt 含候选连接，输出也长；默认 4096 上下文容易把 JSON 截断。
ROUTE_NUM_CTX = int(os.environ.get("P07_ROUTE_NUM_CTX", "8192"))
