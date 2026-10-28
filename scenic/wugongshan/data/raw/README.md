# 原始页面说明

为保证仓库体积和尊重原站版权，**没有提交 14 个页面的完整 HTML 快照**，只保留：

- `manifest.csv`：每条记录的 URL、HTTP 状态、字节数、编码、抓取时间、SHA256；
- `config/sources.csv`：14 条采集清单；
- `src/collect.py`：采集脚本，可按清单重新抓取。

重新生成原始页面（在 `武功山/` 目录下）：

```powershell
python src/collect.py
```

运行后会生成 `data/raw/html/WGS-O-01.html` … `WGS-T-08.html`。由于站点可能改版或删帖，
重新抓取的内容与 `manifest.csv` 中的 SHA256 不一定完全一致；`manifest.csv` 记录的是
2026-10-28 采集时的状态。

页面仅用于课程实验，版权归原网站/作者所有。
