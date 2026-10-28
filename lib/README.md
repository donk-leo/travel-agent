# 共享代码（唯一实现）

> 这里的代码被 `checks/`、各景区脚本、各分析项目共同引用。
> **禁止把这里的逻辑复制到各项目里改**——需要扩展就改这里并走 PR（维护人：T0coke）。

| 文件 | 作用 |
|---|---|
| `paths.py` | 全仓库路径常量（根目录、各项目输出路径）。所有脚本只从这里取路径，禁止硬编码相对路径拼字符串。 |
| `io_utils.py` | 统一读写：CSV（UTF-8-SIG）、JSONL、JSON。 |
| `schema.py` | 字段常量、`doc_id` 解析、`clean_hash` 计算、行级校验。 |
| `clean_rules.py` | 可复用的清洗原语（HTML 标签、emoji/私有区字符、空白与标点统一）。各景区按需组合，不强制全用。 |

## 用法

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 指向仓库根
from lib.paths import ROOT, scenic_csv
from lib.io_utils import read_csv_sig, write_jsonl
from lib.schema import SCENIC_COLUMNS, clean_hash
```

> 各脚本应保证：从仓库根或项目目录运行时都能 import 到 `lib`（上面这种 `sys.path` 注入是允许的写法）。
