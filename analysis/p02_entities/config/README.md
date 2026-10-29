# P2 实体识别配置

本目录保存基于 Jieba 的第一版领域配置。词典服务于三个固定类别：`POI`、`TRANSPORT`、`TIME`。

- `entity_lexicon.csv`：可读、可审查的主词典；记录景区归属、别名和归一化名称；
- `jieba_userdict.txt`：供 Jieba 直接加载的词典，格式为“词语 词频 词性”；
- `stopwords.txt`：只用于过滤泛化 POI 候选，不用于删除交通或时间表达；
- `time_patterns.md`：时间实体的正则口径与边界。

词典中的 `scenic_area=*` 表示跨景区通用词。短称保留在词典中以保证切分完整，但输出阶段应使用
`normalized_name` 统一名称。新增词条先加到 `entity_lexicon.csv`，再同步到 `jieba_userdict.txt`。

本轮仅建立可复现的词典与规则；识别程序会在后续步骤实现，并统计词条实际命中情况。
