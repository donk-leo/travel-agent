# 景区游览指南的程序性知识挖掘

《数据挖掘》探索性实验 · 三人小组仓库 · 2026-2027-01

从**景区官方攻略与游客游记**中抽取程序性知识（景点 POI、交通方式、时间节点、路线顺序、条件建议），
构建知识图谱，最终实现旅游规划 Agent。共 7 个实验项目 + 总结反思，**2026-11-20 24:00 前提交**。

> **新成员 / 新 Agent 请先读 [`AGENTS.md`](AGENTS.md)**，再读 [`docs/02_协作流程.md`](docs/02_协作流程.md)。
> 每个项目的输入输出契约在 [`standards/handover/`](standards/handover/)。

---

## 项目状态

| # | 项目 | 主责 | 状态 | 产出 | 交付 tag |
|---|---|---|---|---|---|
| 1 | 数据采集与预处理 | 三人各自负责一景区 | 长隆 ✅（8 条）｜白云山 ✅（7 条）｜武功山 ✅（14 条） | `scenic/*/data/processed/*_guides.csv` + `scenic/summary/` | 待补白云山脚本后打 `v0.1-p01` |
| 2 | 实体识别 | T0coke | 未开始 | `analysis/p02_entities/outputs/entities.jsonl` | — |
| 3 | 路线层级结构 | HappinessJo | 未开始 | `analysis/p03_routes/outputs/routes.jsonl` | — |
| 4 | 共指消解 | 成员3 | 未开始 | `analysis/p04_coref/outputs/coref.jsonl` | — |
| 5 | 条件建议抽取 | T0coke | 未开始 | `analysis/p05_conditions/outputs/conditions.jsonl` | — |
| 6 | 知识图谱 | T0coke | 未开始 | `analysis/p06_graph/outputs/graph_*.csv` | — |
| 7 | 旅游规划 Agent | HappinessJo | 未开始 | `analysis/p07_agent/src/agent.py` | — |
| — | 总结反思 | 三人 | 未开始 | `report/章节/总结反思.md` | — |

图例：✅ 已交付并打 tag｜🚧 进行中｜❌ 缺数据｜未开始

---

## 目录结构

| 路径 | 内容 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **共同行为准则**（Agent 与人都适用） |
| [`docs/`](docs/) | 规范文档：统一规范、协作流程、**交接标准**、决策记录、迁移记录 |
| [`standards/`](standards/) | 机器可读契约：各项目 schema + 交接卡 `handover/*.yaml` |
| [`lib/`](lib/) | 共享代码（路径、读写、schema 校验、清洗原语） |
| [`checks/`](checks/) | 质量门：`check_scenic.py` / `check_entities.py` / … |
| [`scenic/`](scenic/) | 项目 1 数据层：`changlong/`、`baiyunshan/`、`wugongshan/` |
| [`analysis/`](analysis/) | 项目 2–7 跨景区分析：`p02_entities/` … `p07_agent/` |
| [`report/`](report/) | 章节模板与总报告装配区 |
| [`archive/`](archive/) | 冻结归档（整理前的临时采集产物） |

---

## 快速开始

```powershell
git clone https://github.com/donk-leo/travel-agent.git 团队仓库
cd 团队仓库
python -m pip install -r requirements.txt

# 1) 项目1 数据自检（三景区任一）
python checks/check_scenic.py scenic/wugongshan/data/processed/wugongshan_guides.csv

# 2) 武功山全链路重跑（复用已抓 HTML，约 10-20 秒）
cd scenic/wugongshan
python src/run_all.py
```

---

## 三人分工

| 成员 | 负责景区 | 项目主责 | 复核 |
|---|---|---|---|
| **HappinessJo** | 长隆旅游度假区 | P3 路线层级、P7 Agent、文档与准则 | P2 / P6 |
| **T0coke** | 萍乡武功山 | P2 实体识别、P5 条件建议、P6 知识图谱、公共层 | P3 / P7 |
| **成员3（待填）** | 广州白云山 | P4 共指消解 | P5 |

规则：**一个项目只有一个 owner；owner 不同时做 reviewer。**

---

## 交接一句话

> 产出写死文件名 → `checks/check_pNN_*.py` 跑绿 → 更新 `standards/handover/pNN_*.yaml` 的 `status` → 打 tag 推送。
> 四条做完才算交付；tag 之后 `doc_id`、`clean_content`、枚举、span 口径即冻结。

详见 [`docs/03_交接标准.md`](docs/03_交接标准.md)。

---

## 合规与版权

- 仅采集公开可访问页面，遵守 robots.txt，请求间隔 ≥ 2 秒，不绕登录与验证码；
- 数据仅用于课程实验，版权归原网站/作者所有，引用请标注来源链接；
- 需登录态才能获取的数据（如小红书）在 `scenic/*/README.md` 中单独标注可复现性限制。
