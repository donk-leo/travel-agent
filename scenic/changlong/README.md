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
| 原始 / 清洗后字数 | 28,000+ / 11,019（去空白口径见 csv 的 `char_raw` / `char_clean`） |
| 有效记录 | 8/8（`is_valid=True`） |

> 说明：本目录的数据由本地历史数据集（20 列英文结构）转换而来，转换脚本
> `src/export_standard.py` 与输入 `data/interim/legacy_20col.csv` 一并提交，可完整复现。

## 2. 目录

```
changlong/
├─ src/export_standard.py         # 20 列 -> 24 列标准格式（本仓库唯一转换入口）
├─ data/
│  ├─ raw/manifest.csv            # 8 个原始页面的 URL / 状态 / 字节 / SHA256 / 采集时间
│  ├─ interim/legacy_20col.csv    # 转换前数据（含 raw_text/clean_text）
│  └─ processed/changlong_guides.csv   ★ 交付物（24 列，UTF-8-SIG）
├─ outputs/                       # 质量报告、清洗前后对比（待补）
└─ report/                        # 实验报告章节 docx（待放）
```

## 3. 复现

```powershell
# 从仓库根执行
python scenic/changlong/src/export_standard.py
python checks/check_scenic.py scenic/changlong/data/processed/changlong_guides.csv
```

预期：8 条记录，`官方 3 / 有效游记 5`，检查通过。

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
