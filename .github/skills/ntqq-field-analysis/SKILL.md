---
name: ntqq-field-analysis
description: "分析 NTQQ 数据库字段含义的三阶段工作流。使用场景：对 nt_msg_plain.db 的 c2c_msg_table 中某个或多个未知字段进行逆向分析；生成临时分析报告供用户审阅；用户确认后写入 field/XXXXX.md 最终报告并更新 field/table.md。触发词：分析字段、字段含义、逆向分析、字段报告、写入报告、更新table.md。"
argument-hint: "字段编号，例如：40002 或 40002+40005（联合分析）"
---

# NTQQ 字段分析工作流

## 概述

三阶段流程：**编写分析脚本 → 运行生成临时报告 → 用户确认后写入最终报告**。

---

## 阶段一：编写分析脚本

### 1.1 确定分析目标

在开始前，先查阅 [field/table.md](../../../field/table.md) 了解已分析字段及当前假设，避免重复工作。明确：
- 目标字段编号（可多个，联合分析）
- 已有的猜测或上下文线索
- 拟与哪些已知字段交叉验证

### 1.2 脚本规范

脚本名：`analyze_XXXXX.py`（多字段联合：`analyze_XXXXXxYYYYY.py`）  
输出文件：`analysis_XXXXX.md`（临时报告，不是最终报告）

```python
"""
分析：XXXXX [× YYYYY]

目标：
  1. ...
  2. ...
"""
import sqlite3
import pathlib
import datetime
import statistics
import collections

PLAIN_DB  = "nt_msg_plain.db"
TABLE     = "c2c_msg_table"
OUTPUT_MD = "analysis_XXXXX.md"

def main():
    conn = sqlite3.connect(PLAIN_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    lines: list[str] = []
    p = lines.append

    # --- 分析逻辑 ---

    output = "\n".join(lines)
    print(output)
    pathlib.Path(OUTPUT_MD).write_text(output, encoding="utf-8")
    print(f"\n[OK] 已写入 {OUTPUT_MD}")

if __name__ == "__main__":
    main()
```

> **注意**：`print()` 中避免 emoji（Windows GBK 终端会报 UnicodeEncodeError），`OUTPUT_MD` 写入使用 `encoding="utf-8"`。

### 1.3 标准分析模块（按需选用）

参见 [references/analysis-modules.md](./references/analysis-modules.md) 获取各模块的 SQL 模板和代码片段。

| 模块 | 适用场景 |
|------|---------|
| 基础统计 | 所有字段 |
| 位掩码分析 | 疑似 bitmask（值为小整数且分散） |
| 时序单调性检验 | 疑似 ID / 序号字段 |
| 交叉矩阵（× 40013） | 分析与消息方向的关系 |
| 交叉矩阵（× 40011/40012） | 分析与消息类型的关系 |
| 消息体大小关联（× 40800） | 判断是否影响消息内容结构 |
| 会话内 vs 全局序号 | 疑似序号字段 |
| Snowflake 时间戳检验 | 疑似时间编码 ID |
| Pearson 相关性 | 数值字段间的线性相关 |
| 样本抽取 | 所有字段（对比 40090/40093/40800 等上下文） |

---

## 阶段二：运行脚本并审阅

```
uv run .\analyze_XXXXX.py
```

运行后将 `analysis_XXXXX.md` 的关键结论展示给用户，包括：
- 字段的最可能含义
- 置信度评估（高 / 中 / 低）
- 异常值 / 边界情况说明

**等待用户确认结论正确，或根据反馈调整脚本重新运行。**

---

## 阶段三：写入最终报告

用户确认后执行以下两步（可并行）：

### 3.1 创建 field/XXXXX.md

参照 [references/field-report-template.md](./references/field-report-template.md) 撰写，包含：
- 字段属性表（编号、类型、主键、置信度）
- 含义说明
- 取值说明表
- 分布统计
- 关联字段
- 验证方法（如有）

> **隐私保护要求**：报告中出现的所有真实 QQ 号、NT UID、昵称等个人信息必须模糊化处理，禁止以明文写入最终报告。
>
> | 信息类型 | 处理规则 | 示例 |
> |---------|---------|------|
> | QQ 号（9位以下）| 保留前2位和后2位，中间替换为 `****` | `84****14` |
> | QQ 号（9位及以上）| 保留前3位和后2位，中间替换为 `****` | `840****14` |
> | NT UID | 保留 `u_` 前缀后4个字符，其余替换为 `****` | `u_B5T2****` |
> | 昵称 / 备注 | 替换为 `<昵称已隐去>` | — |
> | 具体时间戳（精确到秒的真实值）| 仅保留年月精度或替换为相对描述 | `2025-11` |

### 3.2 更新 field/table.md

找到对应字段行，更新以下列：
- 置信度：`❓ 低` → `🔍 中` 或 `✅ 高`
- 简称
- 概述
- 详细报告链接（`[XXXXX.md](XXXXX.md)`）

同时在末尾"已分析字段汇总"表中追加一行，填写字段、简称、置信度、分析脚本名。
