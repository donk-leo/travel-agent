# P2 实体识别人工抽查说明

抽查文件：`manual_review_samples.csv`（30 条；POI、TRANSPORT、TIME 各 10 条）。

## 如何复核

1. 查看 `entity_text` 是否与 `clean_content_full[char_start:char_end]` 完全一致；
2. 查看 `source_sentence` 和 `source_excerpt`，判断实体类型是否正确；
3. 在 `manual_verdict` 填写“正确”或“错误”；
4. 若错误，在 `issue_type` 填写“误识别 / 类型错误 / 位置错误 / 归一化错误 / 其他”；
5. 如有修正意见，填写 `suggested_correction` 与 `reviewer_note`。

## 结论口径

- `POI`：具体景区、子园区、景点、入口、设施或有明确名称的游乐项目；
- `TRANSPORT`：乘坐或移动方式，例如地铁、缆车、索道、观光车、步行；
- `TIME`：时刻、时段、游览时长、日期/季节区间或行程天数；
- “景区”“路线”“这里”等没有专名意义的泛词应判为误识别；
- `12:10`、`3-4小时`、`两天一夜` 等明确时间表达应判为正确的 `TIME`。

误识别率计算：`错误条数 / 30`。交接标准建议误识别率低于 15%。
