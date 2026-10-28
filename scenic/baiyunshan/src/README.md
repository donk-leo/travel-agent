# 白云山数据生成说明

本目录数据由 T0coke 按 `docs/01_统一规范.md` 代整理，待白云山负责人复核后转正。

## 输入

- 平台原始 CSV：`archive/legacy_collect_2026-10-28/采集结果.csv`、`小红书采集结果.csv`
  （白云山 7 条：去哪儿 1 条、小红书 3 条、官方 3 条）
- 官方路线页面：`data/raw/sources.csv` 中 BYS-O-01..03 的 URL

## 处理

1. 去哪儿记录标为 `站点攻略`；小红书标为 `游客游记`；
2. 小红书原“正文”是整页文本，按笔记标题最后一次出现截取正文；纯图片/视频笔记剔除；
3. 清洗沿用项目1的 R1–R8 规则，另加官网菜单、去哪儿“发布时间”、小红书页脚等平台噪声规则
   （实现见 `scenic/wugongshan/src/clean.py` 与 `scenic/summary/src/` 的说明）；
4. 24 列字段与 `standards/schema_scenic.json` 对齐，输出 UTF-8-SIG。

## 校验

```powershell
python checks/check_scenic.py scenic/baiyunshan/data/processed/baiyunshan_guides.csv
```

预期：7 条，官方 3 / 有效游记 3，通过。

## 注意

- 小红书 `source_url` 带 `xsec_token`，过期后需重新登录获取；
- 官方 B/C 线原文仅 63/64 字，项目 3 解析时建议优先用 A 线（395 字）。
