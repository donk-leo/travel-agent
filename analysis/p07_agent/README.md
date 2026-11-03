# 项目 7：旅游规划 Agent

项目 7 读取项目 6 的图谱，结合本地 Ollama 模型，提供旅游需求理解、图谱查询、路线建议及来源展示。项目已通过用户审核，交付版本为 `v0.7-p07`；已知限制留待后续优化。

## 环境

- Python 3.9 或以上；本次实际环境：Python 3.9.6、Flask 3.1.3。
- Ollama 服务可用，并已下载 `qwen3:8b`：

```bash
ollama pull qwen3:8b
python3 -m pip install -r analysis/p07_agent/requirements.txt
```

启动前请确保 Ollama 服务正在运行。默认地址为 `http://localhost:11434/api/chat`，默认模型为 `qwen3:8b`。使用本地 Ollama 不需要 OpenAI API 密钥。

可选的环境变量见 `.env.example`。例如，在启动程序的终端中执行：

```bash
export P07_OLLAMA_URL=http://localhost:11434/api/chat
export P07_OLLAMA_MODEL=qwen3:8b
```

程序读取进程环境变量，不会自动加载 `.env` 文件；不配置时使用上述默认值。

## 启动网页

在仓库根目录执行：

```bash
python3 analysis/p07_agent/src/web_app.py
```

打开终端显示的本地地址，输入需求，例如“我想带孩子和老人去长隆玩一天，喜欢游乐项目，尽量少走路”。规划需求缺少景区或天数时会追问；可以点击“开始新需求”清除当前追问上下文。网页可展开查看决策摘要、图谱来源和工具调用记录。

## 重跑检查和案例

在仓库根目录执行：

```bash
python3 -m unittest discover -s analysis/p07_agent/tests -v
python3 analysis/p07_agent/src/run_evaluation.py
python3 checks/check_agent.py analysis/p07_agent/
```

第一条是离线流程测试，使用模拟模型和真实图谱；第二条实际调用本地模型，覆盖亲子、老人、朋友、伴侣、信息不足、冲突、无匹配及地点列表，可能需要数分钟。它会生成 `outputs/evaluation_results.json` 和新的 `outputs/sessions/*.jsonl`。这些案例是人工编写的测试输入，不是原始游记数据。第三条检查约定的交付文件。

评估脚本是一条命令重跑案例，不等于保证语言模型逐字输出一致；模型版本、推理环境及图谱版本可能影响结果。`outputs/tests.md` 和 `outputs/demo.md` 记录了本次运行与人工分析，不会在每次重跑后自动重写。

## 流程和输入

`src/agent.py` 是主流程：需求解析 → 决定追问/回复/查图谱 → 需求检查 → 模型选择工具 → 读取工具结果并决定是否补查（最多 3 轮）→ 方案检查 → 返回结果及会话记录。行程规划需要路线证据；如果模型漏选路线查询，系统会补充调用并单独记录。模型只看到本次工具返回的相关数据和摘要，不把整个图谱直接写入提示词。

- 图谱只读：`analysis/p06_graph/outputs/graph_nodes.csv`、`graph_edges.csv`，来源标签 `v0.6-p06`。
- `tools.py` 提供 `search_poi`、`get_route`、`get_conditions`、`neighbors` 及按来源分组的 `get_route_candidates`。
- `route_planner.py` 根据候选图谱连接规划，使用 `validate_route` 检查方向；直接连接缺失时可搜索间接 `NEXT` 路径。返回分岔点可以重复，并给出提示。
- `constraint_checker.py` 在规划前和最终方案输出前进行模型检查；模型会误判，检查不能保证覆盖全部限制。
- `trace_log.py` 保存 JSONL。新版记录包含用户输入、意图、决策摘要、工具参数及观察、最终结果；旧版记录可能只含工具调用。会话记录会包含请求文字，分享前应检查内容。

工具接口见 `standards/schema_tools.json`。v1.2 在此前确认的 `get_route` 来源字段基础上，明确补充现有的 `get_route_candidates` 分组接口；未更改 P6 图谱。

## 已知限制

- `NEXT` 表示来源资料中的步骤顺序，并非现场道路网络；缺少实际距离、坡度和通行情况，不能仅据此保证少走路或某天能完成。
- 两天请求目前没有稳定的逐日安排；预算、日出时间、适龄性和活动开放情况缺少完整数据，模型推测及历史来源信息不能当作实时核实。
- 有时会漏掉“朋友”等人群；景区简称和子园区归属、组合路线中的重复路段仍待后续优化。
- 图谱地点列表基于既有抽取，可能包含车站、餐厅、噪声或遗漏，不是官方完整景点名录。
- 模型工具选择、理由生成和冲突检查可能误判；无匹配只说明图谱中没有查到，不能断言现实中不存在。

当前实验记录、示范及报告分别见 `outputs/tests.md`、`outputs/demo.md`、`report/p07_experiment_report.md`。审核结论及 reviewer 字段的说明见 `standards/handover/p07_agent.yaml`。
