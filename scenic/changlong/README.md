# 长隆旅游度假区（广州长隆）· 项目 1

> 负责人：**HappinessJo**｜交接卡：`standards/handover/p01_scenic.yaml`｜数据 schema：`standards/schema_scenic.json`
> 目录内所有文件只由本景区负责人修改，其他人只读。

## 1. 数据概况

| 项 | 结果 |
|---|---|
| 景区 | 长隆旅游度假区（广州长隆），含 4 个子园区 |
| 记录数 | 8 条（官方路线 3 条 + 游客游记 5 篇） |
| 子园区 | 野生动物世界、欢乐世界、水上乐园、度假区（多园区） |
| 来源 | 长隆官网「行程推荐」（3 篇）+ Trip.com 旅行笔记（5 篇，不同作者） |
| 采集日期 | 2026-10-28 |
| 原始 / 清洗后字数 | 12,247 / 10,678（去空白纯文本，口径见 `docs/01_统一规范.md` 第 1 节） |
| 有效记录 | 8/8（`is_valid=True`） |

> **字数口径说明（2026-10-28 修正）**：`raw_content` 原先直接存官网 innerHTML，含 468/186/241 个样式标签，
> 导致 `char_raw` 虚高（28,385）且与武功山、白云山的纯文本口径不可比。现已改为
> “去标签后的纯文本、保留模板噪声”，与另外两个景区一致；删标签属于**抽取**，不计入 `removed_char_ratio`。
>
> 因此三个数字要分清：
> - **本表 12,247 / 10,678**：跨景区可比口径（用于汇总与质检）；
> - **实验报告 docx 里的 29,975 → 11,019（削减 63.2%）**：旧口径，把 HTML 标签算进“原始内容”，
>   二者内部各自自洽，但**不要把两个口径的数字混在一张表里**。
>
> 说明：本目录的数据由本地历史数据集（20 列英文结构）转换而来，转换脚本
> `src/export_standard.py` 与输入 `data/interim/legacy_20col.csv` 一并提交，可完整复现。

## 2. 目录

```
changlong/
├─ src/
│  ├─ run_all.py                # ★一键流水线：清洗 → 质检 → 导出 → 自检（--refresh 重新采集）
│  ├─ collect_pages.py          # 采集 8 个页面：落 HTML + raw_docs.jsonl + manifest(SHA256)
│  ├─ clean_dataset.py          # R1–R10 十条清洗规则 → legacy_20col.csv + 质量指标
│  ├─ qc_dataset.py             # 3 张图 + 质量检查报告 + 可用性标记
│  ├─ export_standard.py        # 20 列 → 24 列标准格式（交付物）
│  ├─ test_rules.py             # 清洗规则自测（11 项）
│  └─ build_report.py           # 生成实验报告章节 docx
├─ data/
│  ├─ raw/manifest.csv          # 8 个原始页面的 URL / 状态 / 字节 / SHA256 / 采集时间
│  ├─ raw/*.html                # 原始快照（.gitignore 忽略，--refresh 可重取）
│  ├─ interim/raw_docs.jsonl    # 采集结果（已提交，默认流水线从这里开始）
│  ├─ interim/legacy_20col.csv  # 清洗后的 20 列中间表
│  └─ processed/changlong_guides.csv   ★ 交付物（24 列，UTF-8-SIG）
├─ outputs/                     # 质量检查报告.md、清洗前后样例、quality_report.json、图表
└─ report/                      # 实验报告章节 docx
```

## 3. 复现（一条命令）

```powershell
# 从仓库根执行：复用已提交的 raw_docs.jsonl，不联网
python scenic/changlong/src/run_all.py

# 完整重采集（8 个页面，请求间隔 1.2s，约 10 秒）
python scenic/changlong/src/run_all.py --refresh

# 可选：重新生成报告章节
python scenic/changlong/src/build_report.py
```

预期：`check_scenic` 输出 `8 条，官方 3 / 有效游记 5，通过`。
`run_all.py` 会依次执行 clean → qc → export → check，任一步失败即中断并给退出码。

> 已验证：从 `raw_docs.jsonl` 重跑得到的 `changlong_guides.csv` 与仓库中版本**逐字节一致**。

## 4. 原始 HTML 说明

原始页面快照**未提交**（体积大），仅以 `data/raw/manifest.csv` 记录 URL 与 SHA256。
需要重新获取时，用历史采集脚本（`experiment1_chimelong/scripts/collect_chimelong.py`，请求间隔 1.2s、
固定 UA、3 次重试）重跑，或按 manifest 的 URL 手工保存后校验 SHA256。

## 5. 已知限制

1. 官网 3 篇的页内日期较早（2019/2023/2024），项目名与票价可能已变更，价格类信息不作为知识事实；
2. 游记 `CL-T-05`（水上乐园）清洗后仅 406 字，信息密度低，已保留并标 `子园区:水上乐园`；
3. 原文多为繁体（Trip.com 港澳台站点），清洗阶段已统一转简体，个别粤语用词保留原貌；
4. 官方页 `CL-O-01` 含“关于饮食/住宿/交通”等非路线段落，项目 3 解析时需按小标题切分。

## 6. 下一步（项目 3 用）

`clean_content` 已冻结；`CL-O-02` 同时具备“箭头链路 + 第一站（时间）”两种格式，适合作为解析样本。
