# 质量门（checks）

> 每个实验项目一个检查脚本。**退出码 0 = 通过**，是"交付完成"的客观标准。
> 维护人：T0coke（新增/修改脚本走 PR）。

| 脚本 | 对应项目 | 检查内容 | 未产出时 |
|---|---|---|---|
| `check_scenic.py` | P1 数据 | 9 个必需列、`doc_id` 格式与唯一、`doc_type` 枚举、`clean_content` 长度、`clean_hash` 重复、官方≥1/有效游记≥3 | 报"文件不存在"（**不通过**，P1 是基础） |
| `check_entities.py` | P2 实体 | 字段、类型枚举、span 合法、`entity_text` 与 `clean_content` 精确对应、重复 | 提示"尚未产出"，退出 0 |
| `check_routes.py` | P3 路线 | `step_no` 连续唯一、`time_source` 枚举、absent 不得填 `time_norm` | 同上 |
| `check_coref.py` | P4 共指 | 字段、方法枚举、代词 span、标注 ≥5 条、`eval.md` | 同上 |
| `check_conditions.py` | P5 条件 | 字段、类型枚举、`cond_id` 唯一、条件/建议为原文子串、映射表 | 同上 |
| `check_graph.py` | P6 图谱 | 节点/边字段与枚举、边端点存在、最大连通分量 ≥50%、`graph_qa.md` | 同上 |
| `check_agent.py` | P7 Agent | 入口/工具、会话轨迹、测试与示范、`.env` 未提交、无明文密钥 | 同上 |

## 统一用法

```powershell
python checks/check_scenic.py scenic/changlong/data/processed/changlong_guides.csv
python checks/check_entities.py                     # 默认路径
python checks/check_graph.py analysis/p06_graph/outputs
```

## 约定

- 所有脚本只读、不修改数据；
- 新增检查项必须同步更新 `docs/03_交接标准.md` 的验收清单；
- 报告统一格式：`=== 标题 —— 通过/不通过 ===`，逐条 `[错误]` / `[警告]`。
