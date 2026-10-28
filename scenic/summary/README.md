# 项目 1 三景区汇总（scenic/summary）

本目录把 `scenic/changlong`、`scenic/baiyunshan`、`scenic/wugongshan` 三个已冻结的
24 列数据集合并为一份跨景区数据层，并给出质量检查、Excel 与项目1小组报告。

> 本目录**不重新清洗、不修改**三个景区的 `clean_content`；只读上游 CSV，做合并、去重、统计。
> 三个景区数据的维护人分别是 HappinessJo（长隆）、成员3（白云山，待复核）、T0coke（武功山）。

## 1. 汇总结果

| 景区 | 记录数 | 官方路线 | 游客游记 | 站点攻略 | 有效游客游记 | 来源 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 长隆 | 8 | 3 | 5 | 0 | 5 | 长隆官网、Trip.com |
| 广州白云山 | 7 | 3 | 3 | 1 | 3 | 白云山官网、小红书、去哪儿 |
| 武功山 | 14 | 6 | 8 | 0 | 7 | 武功山官网、豆瓣、8264、简书、搜狐 |
| **合计** | **29** | **12** | **16** | **1** | **15** | — |

- 原始 48,356 字，清洗后 29,866 字；有效记录 28 条。
- 三个景区均满足“官方路线 ≥1 + 有效游客游记 ≥3”，已通过 `checks/check_scenic.py`。
- 作者缺失 6 条、日期缺失 4 条，均写“未知”并打质量标记，未伪造。

## 2. 输出

```
scenic/summary/
├─ data/
│  ├─ 三景区汇总数据集.csv      # 29 条 × 24 列，UTF-8-SIG
│  └─ 三景区汇总统计.csv
├─ outputs/
│  ├─ 三景区质量检查.md
│  ├─ 清洗前后对比.md
│  ├─ 统计摘要.json
│  └─ 三景区景区指南数据集.xlsx  # 7 个工作表
├─ report/
│  ├─ 项目1_三景区…docx / pdf
│  └─ figures/                  # 3 张插图
└─ src/
   ├─ build_summary.py          # 读取三景区 CSV → 合并/去重/统计
   ├─ qc_summary.py             # 质检 Markdown + Excel
   ├─ make_summary_figures.py   # 插图
   └─ build_summary_report.py   # 报告 docx
```

## 3. 复现

```powershell
cd scenic/summary
python src/build_summary.py
python src/qc_summary.py
python src/make_summary_figures.py
python src/build_summary_report.py
python ../../checks/check_scenic.py data/三景区汇总数据集.csv
```

依赖：Python 3.11+、pandas、openpyxl、python-docx、Pillow。

## 4. 口径说明

1. **只读上游**：三个景区的 `doc_id`、`clean_content`、`is_valid` 原样保留；汇总只按
   `clean_hash` 去重（本次 29 条无重复）。
2. **站点攻略**：去哪儿页面是平台编辑的 SEO 攻略，统一标为 `站点攻略`，不计入“有效游客游记”。
3. **缺失值**：白云山/武功山部分小红书页面无作者、无法确认发布日期，统一写“未知”，
   在 `quality_flags` 中标注。
4. **长隆**：由负责人按本地历史数据集转换为 8 条（3 官方 + 5 游记），本汇总不重复补采。
5. **白云山**：由 T0coke 代整理 7 条（3 官方 A/B/C 线 + 3 小红书游记 + 1 去哪儿站点攻略），
   待白云山负责人复核后转正。

## 5. 与项目 2 的衔接

项目 2 起，所有下游只读 `clean_content`（字符位置从 0 开始、结束位置不含）。
本汇总 CSV 可直接作为三景区实体识别的输入；`doc_id`、`scenic_area`、`doc_type` 可用于分组统计。
