# 分析模块 SQL 与代码模板

以下代码片段可直接复制到 `analyze_XXXXX.py` 的 `main()` 中。`cur`、`conn`、`lines`、`p` 变量与主脚本一致。

---

## 基础统计

```python
p("## 1. 基础统计\n")
cur.execute(f'''
    SELECT
        COUNT(*) AS total,
        COUNT(DISTINCT "{F}") AS uniq,
        SUM(CASE WHEN "{F}" IS NULL THEN 1 ELSE 0 END) AS null_cnt,
        MIN("{F}") AS mn,
        MAX("{F}") AS mx
    FROM {TABLE}
''')
r = cur.fetchone()
p(f"- 总行数：{r['total']:,}")
p(f"- 不重复值数：{r['uniq']:,}")
p(f"- NULL 行数：{r['null_cnt']:,}")
p(f"- 值域：{r['mn']} ～ {r['mx']}\n")

# 取值频率分布（TOP 30）
cur.execute(f'''
    SELECT "{F}", COUNT(*) AS cnt
    FROM {TABLE}
    GROUP BY "{F}"
    ORDER BY cnt DESC
    LIMIT 30
''')
dist = cur.fetchall()
total = sum(r["cnt"] for r in dist)
p("| 值 | 行数 | 占比 |")
p("|----|------|------|")
for r in dist:
    p(f"| `{r[F]}` | {r['cnt']:,} | {r['cnt']/total*100:.2f}% |")
p("")
```

---

## 位掩码分析（Bitmask）

```python
p("## 位掩码分析\n")
cur.execute(f'SELECT "{F}" FROM {TABLE} WHERE "{F}" IS NOT NULL')
all_vals = [r[F] for r in cur.fetchall()]
bit_counts = collections.defaultdict(int)
for v in all_vals:
    for b in range(16):
        if v & (1 << b):
            bit_counts[b] += 1
total_vals = len(all_vals)
p("| Bit | 掩码值 | 出现次数 | 出现率 |")
p("|-----|--------|---------|--------|")
for b in range(16):
    cnt = bit_counts[b]
    if cnt > 0:
        p(f"| bit{b} | `0x{1<<b:04X}` ({1<<b}) | {cnt:,} | {cnt/total_vals*100:.2f}% |")
p("")
```

---

## 与 40013（消息方向）交叉矩阵

```python
p("## × 40013 方向交叉\n")
cur.execute(f'''
    SELECT "{F}", "40013", COUNT(*) AS cnt
    FROM {TABLE}
    GROUP BY "{F}", "40013"
    ORDER BY "{F}", cnt DESC
''')
rows = cur.fetchall()
import collections as col
matrix = col.defaultdict(list)
for r in rows:
    matrix[r[F]].append((r["40013"], r["cnt"]))
p("| {F} 值 | 方向分布（40013: 次数） |")
p("|--------|----------------------|")
for val, pairs in sorted(matrix.items()):
    detail = ", ".join(f"{d}:{c:,}" for d, c in pairs)
    p(f"| `{val}` | {detail} |")
p("")
```

---

## 消息体大小关联（× 40800）

```python
p("## × 40800 消息体大小\n")
cur.execute(f'''
    SELECT
        "{F}",
        COUNT(*) AS cnt,
        AVG(LENGTH("40800")) AS avg_len,
        MIN(LENGTH("40800")) AS min_len,
        MAX(LENGTH("40800")) AS max_len,
        SUM(CASE WHEN "40800" IS NULL THEN 1 ELSE 0 END) AS null_cnt
    FROM {TABLE}
    GROUP BY "{F}"
    ORDER BY cnt DESC
''')
p("| 值 | 行数 | 均值(B) | 最小(B) | 最大(B) | NULL数 |")
p("|----|------|--------|--------|--------|-------|")
for r in cur.fetchall():
    avg = f"{r['avg_len']:.0f}" if r["avg_len"] else "—"
    p(f"| `{r[F]}` | {r['cnt']:,} | {avg} | {r['min_len']} | {r['max_len']} | {r['null_cnt']:,} |")
p("")
```

---

## 会话内 vs 全局序号检验

```python
p("## 会话内 vs 全局序号检验\n")
# 各会话的字段范围
cur.execute(f'''
    SELECT "40030",
           COUNT(*) AS cnt,
           MIN("{F}") AS mn,
           MAX("{F}") AS mx
    FROM {TABLE}
    GROUP BY "40030"
    ORDER BY cnt DESC
    LIMIT 15
''')
convs = cur.fetchall()
p("| 对方QQ | 消息数 | 最小值 | 最大值 | 跨度 |")
p("|--------|--------|--------|--------|------|")
ranges = []
for c in convs:
    span = (c["mx"] or 0) - (c["mn"] or 0)
    ranges.append((c["mn"] or 0, c["mx"] or 0))
    p(f"| `{c['40030']}` | {c['cnt']:,} | {c['mn']} | {c['mx']} | {span:,} |")
p("")
overlap = sum(
    1 for i,(a0,a1) in enumerate(ranges)
    for j,(b0,b1) in enumerate(ranges) if i < j and a0 <= b1 and b0 <= a1
)
if overlap > 0:
    p(f"> 跨会话范围重叠 {overlap} 对 → **全局序号命名空间**\n")
else:
    p("> 无重叠 → 可能是会话内独立序号\n")
```

---

## 时序单调性检验

```python
p("## 时序单调性检验\n")
# 按 F 升序，检验 40050 是否单调不减（F 是否与时间正相关）
cur.execute(f'''
    SELECT "{F}", "40050" FROM {TABLE}
    WHERE "{F}" IS NOT NULL AND "40050" IS NOT NULL
    ORDER BY "{F}" ASC LIMIT 2000
''')
rows = cur.fetchall()
ok = fail = 0
prev = None
for r in rows:
    ts = r["40050"]
    if prev is not None:
        if ts >= prev: ok += 1
        else: fail += 1
    prev = ts
ratio = ok / (ok + fail) * 100 if (ok + fail) else 0
p(f"- 按 {F} 升序后 40050 单调不减比例：**{ratio:.1f}%** ({ok}/{ok+fail})\n")
```

---

## Snowflake 时间戳检验

```python
SNOWFLAKE_EPOCHS = {
    "Unix 0 (1970-01-01)": 0,
    "Twitter (2010-11-04)": 1288834974657,
    "Discord (2015-01-01)": 1420070400000,
    "QQ NT (2020-01-01)": 1577836800000,
}
SHIFT = 22
cur.execute(f'SELECT "{F}", "40050" FROM {TABLE} WHERE rowid % 6594 = 0 LIMIT 200')
sample = cur.fetchall()
p("| Epoch | 平均偏差(s) | 中位偏差(s) |")
p("|-------|------------|------------|")
for name, epoch_ms in SNOWFLAKE_EPOCHS.items():
    diffs = [(r[F] >> SHIFT + epoch_ms) / 1000.0 - r["40050"]
             for r in sample if r[F] and r["40050"]]
    if diffs:
        p(f"| {name} | {statistics.mean(diffs):+.1f} | {statistics.median(diffs):+.1f} |")
p("")
```

---

## Pearson 相关性

```python
p("## Pearson 相关性\n")
cur.execute(f'''
    SELECT "{F}", "{G}" FROM {TABLE}
    WHERE "{F}" IS NOT NULL AND "{G}" IS NOT NULL
    ORDER BY rowid LIMIT 5000
''')
pairs = cur.fetchall()
xs = [r[F] for r in pairs]
ys = [r[G] for r in pairs]
mx, my = statistics.mean(xs), statistics.mean(ys)
cov = statistics.mean([(x-mx)*(y-my) for x,y in zip(xs,ys)])
sx, sy = statistics.stdev(xs), statistics.stdev(ys)
pearson = cov / (sx * sy) if sx and sy else 0
p(f"- {F} vs {G} Pearson = **{pearson:.4f}**\n")
```

---

## 样本抽取（多字段对比）

```python
p("## 样本抽取\n")
cur.execute(f'''
    SELECT "{F}", "40013", "40030", "40033", "40050", LENGTH("40800") AS blob_len, "40090"
    FROM {TABLE}
    WHERE "{F}" = ?
    LIMIT 10
''', (target_val,))
p("| 40013 | 40030 | 40033 | 40050 | blob_len | 40090 |")
p("|-------|-------|-------|-------|----------|-------|")
for r in cur.fetchall():
    p(f"| {r['40013']} | {r['40030']} | {r['40033']} | {r['40050']} | {r['blob_len']} | {r['40090'] or ''} |")
p("")
```
