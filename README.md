# NTQQ 聊天数据库解密工具

## 背景

NTQQ（QQ NT 架构）将聊天记录存储在 SQLCipher 4 加密的 SQLite 数据库中（通常命名为 `nt_msg.db`）。文件开头有一段 **1024 字节的自定义头部**，其后才是标准的 SQLCipher 数据库内容。在解密之前必须先剥掉这段头部。

密钥为 16 字节 ASCII 字符串，可通过内存调试等方式从 NTQQ 进程中提取。

https://qqbackup.github.io/QQDecrypt/decrypt/description.html

---

## 文件说明

| 文件 | 用途 |
|------|------|
| `nt_msg.db` | 原始输入，含 1024 字节 NTQQ 自定义头 |
| `nt_msg_clear.db` | 剥头后的 SQLCipher 文件（中间产物） |
| `nt_msg_plain.db` | **最终明文 SQLite**，可直接用任意 SQLite 工具打开 |
| `nt_msg_slim.db` | 以相同密钥重新加密、清空了 `group_msg_table`、并在头部拼接原始 1024 字节头的精简版（SQLCipher 格式，可直接回传 NTQQ） |

---

## 脚本一：`main.py` — 解密并导出明文数据库

### 思路

1. **剥离头部**：跳过 `nt_msg.db` 前 1024 字节，输出 `nt_msg_clear.db`（已存在则跳过）。
2. **验证密钥**：用 `sqlcipher3` 以正确的 PRAGMA 顺序打开加密库，确认密钥可用。
3. **逐表导出**：对每张表采用 **rowid 游标分页**（`WHERE rowid > last ORDER BY rowid LIMIT N`），将数据写入明文 SQLite `nt_msg_plain.db`。
   - 遇到损坏页时自动重连、缩小批次（5000 → 1），单行也读不出则跳过该 rowid，之后恢复批次大小。
   - 支持断点续跑：若输出库已有数据，从 `max(rowid)` 继续而非重跑。
4. **复制索引**：将加密库的索引定义搬到明文库。

### PRAGMA 正确顺序（顺序错误将导致解密失败）

```
PRAGMA cipher_page_size = 4096;   ← 必须在 key 之前
PRAGMA key = '...';
PRAGMA kdf_iter = 4000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
```

### 配置

编辑 `main.py` 顶部：

```python
INPUT_DB  = "nt_msg.db"       # 原始输入
CLEAR_DB  = "nt_msg_clear.db" # 中间产物
OUTPUT_DB = "nt_msg_plain.db" # 明文输出

DB_KEY = "在此粘贴密钥"        # 16 字节 ASCII 密钥
```

### 使用

```bash
uv add sqlcipher3   # 首次运行前安装依赖
uv run python main.py
```

### 后果

- 生成 `nt_msg_clear.db`（中间产物，可删）
- 生成 `nt_msg_plain.db`：**完整明文 SQLite**，无需密钥即可直接用 DB Browser、DBeaver 等工具打开
- 已损坏的页会被自动跳过，丢失极少量行（实测 814 万行中跳过 34 条）

---

## 脚本二：`slim.py` — 生成去除 group_msg_table 的精简版

### 背景

`group_msg_table` 储存群聊消息，数据量可达数 GB，且在旧备份中极易出现页损坏（无法直接 `DELETE`）。该脚本绕开损坏，生成一个去掉群消息但保留全部其他数据的精简版数据库，仍以 SQLCipher 格式封装（方便回传给 NTQQ 使用）。

### 思路

1. 打开 `nt_msg_clear.db`（只读，不修改）。
2. **新建**一个空的 SQLCipher 库（`_slim_work.db`，相同密钥和参数）。
3. 逐表处理：
   - `group_msg_table`：**只建空表结构，不复制任何行**，彻底绕开损坏页。
   - 其余所有表：rowid 游标分页复制，同样具备损坏容错逻辑。
   - `sqlite_sequence` 等 SQLite 内置表：直接跳过（SQLite 引擎自动管理）。
4. 复制索引定义。
5. 从 `nt_msg.db` 读取原始 1024 字节头部，**拼接到新库前面** → 输出 `nt_msg_slim.db`。
6. 自动删除临时工作文件 `_slim_work.db`。

### 配置

编辑 `slim.py` 顶部（与 `main.py` 保持一致即可）：

```python
INPUT_DB   = "nt_msg.db"
CLEAR_DB   = "nt_msg_clear.db"
OUTPUT_DB  = "nt_msg_slim.db"
DB_KEY     = "在此粘贴密钥"
SKIP_TABLE = "group_msg_table"  # 只建空表的表名
```

### 使用

```bash
uv run python slim.py
```

### 后果

- 生成 `nt_msg_slim.db`：SQLCipher 格式，带原始 1024 字节头，`group_msg_table` 为空，其余数据完整
- **`group_msg_table` 的所有消息将不存在于输出文件中**，无法恢复（源库 `nt_msg_clear.db` 不受影响）
- 文件体积比原始 `nt_msg.db` 大幅缩小

---

## 依赖

```
Python 3.10+
sqlcipher3 (uv add sqlcipher3)
```

`sqlcipher3` 包内置 SQLCipher 4 动态库，无需额外安装系统级 sqlcipher。
