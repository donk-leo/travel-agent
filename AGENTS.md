# AGENTS.md —— 本仓库的共同行为准则

> 适用对象：**所有参与本仓库工作的 AI Agent 与新会话**（人类成员也应按此执行）。
> 你在本仓库做的任何事，都必须能从这份文件推导出来。与本文冲突的做法一律视为错误。
> 维护人：HappinessJo｜最后更新：2026-10-29

---

## 0. 先读这三句

1. 这是**三个人 + 多个 Agent 共用的仓库**，你的改动会影响别人，**动手前先读、先确认**。
2. 每个项目的**输入、输出、验收、冻结项**都写在 `standards/handover/pNN_*.yaml`，那是契约，不是建议。
3. 交付 = 产出齐全 + `checks/check_pNN_*.py` 通过 + 打了 tag + `handover.yaml` 里 `status: done`。**四缺一不算交付。**

---

## 1. 项目背景（30 秒）

《数据挖掘》探索性实验：从景区官方攻略与游客游记中抽取**程序性知识**（景点 POI、交通方式、时间节点、
路线顺序、条件建议），构建知识图谱，最终做成旅游规划 Agent。共 7 个实验项目 + 总结反思，
**2026-11-20 24:00 前由组长提交**。

评分五维：功能完成度、方法合理性、结果质量、分析解释、可复现性。
**允许用 LLM 与开源代码，但必须能解释核心逻辑；截图不能替代代码与结果文件。**

---

## 2. 仓库地图（记住这一张图）

```
/
├─ AGENTS.md              ← 本文件（Agent 入口）
├─ README.md              ← 人读总览 + 七项目进度表
├─ requirements.txt       ← 共享依赖
├─ docs/                  ← 规范（人读）
│  ├─ 01_统一规范.md        字段、命名、doc_id
│  ├─ 02_协作流程.md        Git 操作
│  ├─ 03_交接标准.md        七项目交接契约
│  ├─ 04_决策记录.md        为什么这么定
│  └─ 05_迁移记录.md        重整做了什么、怎么回滚
├─ standards/             ← 契约（Agent / 脚本读）
│  ├─ schema_*.json         各项目数据 schema
│  └─ handover/pNN_*.yaml   ★每个项目的交接卡
├─ lib/                   ← 共享代码（唯一实现，禁止复制到别处）
├─ checks/                ← 质量门：每项目一个 check_pNN_*.py
├─ scenic/                ← 项目1 数据层：一人一景区
│  ├─ changlong/  baiyunshan/  wugongshan/
│  └─ summary/            跨景区汇总（29 条 + 汇总报告，T0coke 维护）
├─ analysis/              ← 项目2–7：跨景区，唯一实现
│  ├─ p02_entities/ … p07_agent/
├─ report/                ← 章节模板 + 总报告（只有组长改总报告）
└─ archive/               ← 冻结归档，不参与合并
```

---

## 3. 十条铁律

| # | 铁律 | 为什么 |
|---|---|---|
| 1 | **只改自己负责的目录**（见第 4 节归属表）；公共层改动走 PR | 三人同改必冲突 |
| 2 | **开工先 `git pull`**，只 `git add` 自己的路径 | 忘记拉取会造成覆盖 |
| 3 | **下游只读上游产出**，不读别人的中间文件、不重复清洗 | 版本漂移会让位置/编号全部错位 |
| 4 | **不伪造数据**：不编造游记/攻略、不伪造 URL/时间/指标；模拟数据必须显式标注 | 触碰即挂科 |
| 5 | **数字必须可复算**：报告里的统计量来自脚本输出，不手写 | 评分要求可复现 |
| 6 | **冻结项不能静默改**：`doc_id`、`clean_content`、实体类型枚举、span 口径一旦打 tag 即冻结；要改必须升 tag 并通知全组 | 否则下游全废 |
| 7 | **不提交**密钥、`.env`、cookie、登录态、`__pycache__`、>50MB 文件 | 安全与仓库体积 |
| 8 | **不 `git push -f`**，不删他人分支/提交 | 会造成不可恢复的丢失 |
| 9 | **报告与代码一一对应**：每个结论都能指到具体文件与行 | 评审会抽查 |
| 10 | **做完就更新 `handover.yaml` 和 README 进度表**，不留“做完了但没人知道”的状态 | 交接可见性 |

---

## 4. 角色与文件归属

| 路径 | 唯一维护人 | 其他人 |
|---|---|---|
| `AGENTS.md`、`README.md`、`docs/` | HappinessJo | 提 PR / 提 issue |
| `lib/`、`checks/`、`standards/` | T0coke | 提 PR |
| `scenic/changlong/` | HappinessJo | 只读 |
| `scenic/wugongshan/` | T0coke | 只读 |
| `scenic/baiyunshan/` | 成员3（待填） | 只读 |
| `analysis/p02_entities/`、`p05_conditions/`、`p06_graph/` | T0coke | 主责以外只读 |
| `analysis/p03_routes/`、`p07_agent/` | HappinessJo | 只读 |
| `analysis/p04_coref/` | 成员3 | 只读 |
| `report/总报告_*.docx` | 组长（待定） | 只读 |

**项目分工见 `docs/03_交接标准.md` 第 1 节矩阵；一个项目只有一个 owner，owner 不能兼 reviewer。**

---

## 5. 数据流（谁能读谁）

```
scenic/<area>/data/processed/<area>_guides.csv   （24 列，clean_content 为冻结文本）
   ├─► p02_entities/outputs/entities.jsonl
   ├─► p03_routes/outputs/routes.jsonl
   ├─► p04_coref/outputs/coref.jsonl
   ├─► p05_conditions/outputs/conditions.jsonl
   ├─► p06_graph  （只依赖 p02 + p03 [+ p05]）
   └─► p07_agent  （只依赖 p06 图谱，不直接读原文）
```

- 带字符位置的项目（p02 起）：**以 `clean_content` 为准，起点 0 计，结束位置不含**；
- 任何项目都**不得修改** `scenic/` 下的数据；发现数据有问题 → 报给对应景区负责人，由其升 tag 重出。

---

## 6. 交接协议（Agent 必修）

### 6.1 开工前（3 步）

1. 读本文件 → 读 `standards/handover/pNN_*.yaml`（你要做的那个项目）；
2. 校验输入版本：`handover.yaml` 的 `inputs[].from_tag` 必须存在于 `git tag --list`；
   不存在或对不上 → **停下来问人**，不许自行重跑上游数据；
3. 跑一次项目自检：`python checks/check_pNN_*.py`（未产出时会提示“尚未产出”，属正常）。

### 6.2 交付前（5 条必须全绿）

1. 产出文件齐全且**文件名与 `handover.yaml` 一致**；
2. `checks/check_pNN_*.py` **退出码 0**；
3. 章节稿在 `analysis/pNN_*/report/`（或 `scenic/*/report/`）；
4. 他人 clone 后**一条命令**能跑出同样结果（写进该项目 README）；
5. `handover.yaml` 更新：`status: done`、`version_tag`、`reviewer` 已复核。

### 6.3 交付动作

```powershell
git pull
python checks/check_pNN_xxx.py          # 必须绿
git tag -a v0.N-pNN -m "P N 交付：<一句话>"
git push origin v0.N-pNN
```

打 tag 后，`doc_id` / `clean_content` / 枚举 / span 口径即**冻结**。

---

## 7. 命名规则（违反会被 check 拦下）

| 类别 | 规则 | 例 |
|---|---|---|
| 目录 | 小写 ASCII + `_` | `scenic/wugongshan/`、`analysis/p02_entities/` |
| 项目目录 | `pNN_<英文短名>` | `p03_routes` |
| Python | snake_case，动词开头 | `collect_pages.py`、`parse_routes.py` |
| 项目1 数据 | `<area>_guides.csv`，UTF-8-SIG | `changlong_guides.csv` |
| 项目2–7 产出 | 固定文件名，见 `handover.yaml` | `entities.jsonl`、`graph_nodes.csv` |
| `doc_id` | `<AREA>-<O|T>-<两位>`，**不复用** | `CL-O-01`、`WGS-T-03` |
| 分支 | `<成员>-<任务>` | `happiness-p03-routes` |
| commit | `<范围>: <动作>` | `长隆: 转换 24 列并入库` |

---

## 8. 常用命令

```powershell
# 全仓库自检（能跑的项目会跑，没产出的会跳过）
python checks/check_scenic.py scenic/changlong/data/processed/changlong_guides.csv
python checks/check_entities.py analysis/p02_entities/outputs/entities.jsonl

# 武功山全链路重跑（示例）
cd scenic/wugongshan
python src/run_all.py

# 三景区合并（P1 交付后）
cd scenic/wugongshan
python src/merge_group.py ..\changlong\data\processed\changlong_guides.csv `
                          ..\baiyunshan\data\processed\baiyunshan_guides.csv `
                          data\processed\wugongshan_guides.csv
```

> Python 解释器：Windows 上用 `python` 即可；本机 DSH 环境为
> `C:\Users\32884\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`。

---

## 9. 明确禁止

1. 伪造/改写采集原文、URL、采集时间、评测指标；
2. 把人工补写的文本混入真实语料却不标注；
3. 为指标好看而删除难样本（应保留并标 `is_valid=False` + `quality_flags`）；
4. 未经确认改他人目录、总报告 `.docx`、他人的 `handover.yaml` 结论；
5. `git push -f`、强推、删除他人分支；
6. 在交付目录留临时脚本、日志、`.dsh-office-*` 渲染目录；
7. 把密钥写进代码或提交 `.env`（用 `.env.example` 占位）。

---

## 10. 我要做项目 N，该读哪些文件？

| 任务 | 先读 | 契约 | 自检 |
|---|---|---|---|
| 项目1 某景区数据 | `docs/01_统一规范.md` + 该景区 `README.md` | `standards/handover/p01_scenic.yaml` | `checks/check_scenic.py` |
| 项目2 实体识别 | `docs/03_交接标准.md` 2 节 | `standards/handover/p02_entities.yaml` | `checks/check_entities.py` |
| 项目3 路线层级 | 同上 3 节 | `p03_routes.yaml` | `checks/check_routes.py` |
| 项目4 共指消解 | 同上 4 节 | `p04_coref.yaml` | `checks/check_coref.py` |
| 项目5 条件建议 | 同上 5 节 | `p05_conditions.yaml` | `checks/check_conditions.py` |
| 项目6 知识图谱 | 同上 6 节 | `p06_graph.yaml` | `checks/check_graph.py` |
| 项目7 Agent | 同上 7 节 | `p07_agent.yaml` | `checks/check_agent.py` |
| 总结反思 | `docs/03_交接标准.md` 第 8 节 | — | — |

---

## 11. 当前状态（每次交付后更新）

| 项目 | owner | 状态 | 产出 tag |
|---|---|---|---|
| P1 数据（长隆/白云山/武功山） | 三人各自 | ✅ 三景区齐：长隆 8 / 白云山 7 / 武功山 14 = 29 条（白云山采集脚本待补） | `v0.1-p01` |
| P2 实体识别 | T0coke | ✅ 1006 实体（POI 573 / TIME 248 / TRANSPORT 185） | `v0.2-p02` |
| P3 路线层级 | HappinessJo | ✅ 35 条路线 / 226 个步骤（长隆 8/52、白云山 11/61、武功山 16/113） | `v0.3-p03` |
| P4 共指消解 | 成员3 | 未开始 | — |
| P5 条件建议 | T0coke | 未开始 | — |
| P6 知识图谱 | T0coke | 未开始 | — |
| P7 Agent | HappinessJo | 未开始 | — |
| 总结反思 | 三人 | 未开始 | — |

> 图例：✅ 已交付并打 tag｜🚧 进行中｜❌ 缺数据｜未开始
