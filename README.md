# 灵魂提取器 NTQQ 聊天数据库解密与转换工具

一张通往赛博永生的车票


## 背景

NTQQ（QQ NT 架构）将聊天记录存储在 SQLCipher 4 加密的 SQLite 数据库中（通常命名为 `nt_msg.db`）。文件开头有一段 **1024 字节的自定义头部**，其后才是标准的 SQLCipher 数据库内容。在解密之前必须先剥掉这段头部。

此Repo的所有工作建立在Windows平台上，将个人使用了十八年QQ的完整数据库作为研究对象

密钥为 16 字节 ASCII 字符串，可通过内存调试等方式从 NTQQ 进程中提取。建议使用 PowerShell 脚本提取密钥，2026年5月14日亲测有效

https://qqbackup.github.io/QQDecrypt/decrypt/description.html

## 字段分析文档

- 字段总览：[db_docs/c2c_msg_table/summary.md](db_docs/c2c_msg_table/summary.md)
- 字段文档组目录：[db_docs/c2c_msg_table/](db_docs/c2c_msg_table/)

---

## 文件说明

| 文件 | 用途 |
|------|------|
| `nt_msg.db` | 原始输入，含 1024 字节 NTQQ 自定义头 |
| `nt_msg_clear.db` | 剥头后的 SQLCipher 文件（中间产物） |
| `nt_msg_plain.db` | **最终明文 SQLite**，可直接用任意 SQLite 工具打开 |
| `nt_msg_slim.db` | 以相同密钥重新加密、清空了 `group_msg_table`、并在头部拼接原始 1024 字节头的精简版（SQLCipher 格式，可直接回传 NTQQ） |
| `nt_msg_export.db` | **结构化导出库**，由 `convert.py` 生成，仅含关键字段，支持全文搜索 |

---

## 脚本一：`1.decrypt.py` — 解密并导出明文数据库

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

编辑 `1.decrypt.py` 顶部：

```python
INPUT_DB  = "nt_msg.db"       # 原始输入
CLEAR_DB  = "nt_msg_clear.db" # 中间产物
OUTPUT_DB = "nt_msg_plain.db" # 明文输出

DB_KEY = "在此粘贴密钥"        # 16 字节 ASCII 密钥
```

### 使用

```bash
uv add sqlcipher3   # 首次运行前安装依赖
uv run python 1.decrypt.py
```

### 后果

- 生成 `nt_msg_clear.db`（中间产物，可删）
- 生成 `nt_msg_plain.db`：**完整明文 SQLite**，无需密钥即可直接用 DB Browser、DBeaver 等工具打开
- 已损坏的页会被自动跳过，丢失极少量行（实测 814 万行中跳过 34 条）

---

## 脚本二：`2.slim.py` — 生成去除 group_msg_table 的精简版

### 背景

`group_msg_table` 储存群聊消息，数据量可达数 GB，且在旧备份中极易出现页损坏（无法直接 `DELETE`），在消息管理器中删除所有群聊消息也不会缩小nt_msg.db的大小。该脚本绕开损坏，生成一个去掉群消息但保留全部其他数据的精简版数据库，仍以 SQLCipher 格式封装（方便回传给 NTQQ 使用）。

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

编辑 `2.slim.py` 顶部（与 `1.decrypt.py` 保持一致即可）：

```python
INPUT_DB   = "nt_msg.db"
CLEAR_DB   = "nt_msg_clear.db"
OUTPUT_DB  = "nt_msg_slim.db"
DB_KEY     = "在此粘贴密钥"
SKIP_TABLE = "group_msg_table"  # 只建空表的表名
```

### 使用

```bash
uv run python 2.slim.py
```

### 后果

- 生成 `nt_msg_slim.db`：SQLCipher 格式，带原始 1024 字节头，`group_msg_table` 为空，其余数据完整
- **`group_msg_table` 的所有消息将不存在于输出文件中**，无法恢复（源库 `nt_msg_clear.db` 不受影响）
- 文件体积比原始 `nt_msg.db` 大幅缩小

---

## 脚本三：`3.convert.py` — 导出结构化消息数据库

### 背景

`nt_msg_plain.db` 中的消息内容（`c2c_msg_table.40800` 列）以 Protobuf 编码存储，且夹杂大量未知字段。该脚本解析 Protobuf，提取关键字段，输出一个结构清晰、可直接查询的 SQLite 数据库 `nt_msg_export.db`。

### 思路

1. **只读**打开 `nt_msg_plain.db`，按 `40001`（消息 ID）顺序扫描 `c2c_msg_table`。
2. 用编译好的 `msgdb/msg_pb2.py` 解析每行的 `40800` Protobuf blob。
3. 按 `40011`（消息类型）分发到对应解析函数，提取文本/图片/文件/通话等结构化内容，序列化为 JSON 写入 `content` 列。
4. 批量写入（默认 2000 行/事务），写入期间暂停 FTS5 触发器，全部完成后一次性重建 FTS 索引。

### 输出表结构（`messages`）

| 列 | 来源字段 | 说明 |
|----|---------|------|
| `id` | `rowid` | 原始 c2c_msg_table rowid（主键） |
| `msg_id` | `40001` | 消息唯一 ID（全局单调递增） |
| `timestamp` | `40050` | Unix 秒，服务端发送时间 |
| `direction` | `40013` | 1=发出，0=收到 |
| `sender_uid` | `40020` | 发送方 NT UID（`u_...`） |
| `sender_qq` | `40033` | 发送者 QQ 号 |
| `peer_uid` | `40021` | 会话对象 NT UID |
| `peer_qq` | `40030` | 会话对象 QQ 号 |
| `msg_type` | `40011` | 消息外层类型 |
| `content_type` | `45002` | 内容子类型（首段） |
| `proto_ver` | `49154` | NT 协议版本标识（`"1"` / `"nt_1"`） |
| `inner_ts` | `49155` | 消息内层时间戳（Unix 秒） |
| `text` | `45101` | 所有文本段合并后的纯文本（FTS 全文搜索来源） |
| `content` | `40800` 解析 | JSON，含 `type` 鉴别字段，结构按消息类型而异 |

`content` JSON 示例：

```json
{"type": "text",  "text": "你好"}
{"type": "image", "filename": "xxx.jpg", "width": 1080, "height": 720, "filesize": 204800, "md5_hex": "...", "cdn_url": "..."}
{"type": "file",  "filename": "report.pdf", "filesize": 1048576, "md5_hex": "...", "ext": ".pdf"}
{"type": "call",  "call_type": 7, "duration": 61, "desc": "通话时长 00:01"}
{"type": "mixed", "segments": [...]}
```

支持的 `type` 值：`text` / `image` / `video` / `file` / `sticker` / `contact` / `reply` / `forward` / `legacy_forward` / `call` / `sys` / `mixed`

### 使用

```bash
uv run python 3.convert.py                          # 使用默认路径
uv run python 3.convert.py --src nt_msg_plain.db --dst nt_msg_export.db --batch 5000
uv run python 3.convert.py --debug                  # 显示逐行解析错误详情
```

### 后果

- 生成 `nt_msg_export.db`：标准 SQLite，无需密钥，可直接用 DB Browser 等工具打开
- 自动建立时间、会话、消息类型索引及 FTS5 全文搜索虚拟表（`messages_fts`）
- 实测：131 万行，0 解析错误，约 30 秒完成

---

## 环境配置

### 前置要求

- **Python 3.14**（推荐；`pyproject.toml` 中声明 `requires-python = ">=3.14"`）
- **[uv](https://docs.astral.sh/uv/)**：现代 Python 包管理器，安装方式：
  ```powershell
  # Windows (PowerShell)
  irm https://astral.sh/uv/install.ps1 | iex
  ```

### 安装步骤

```powershell
# 1. 克隆仓库
git clone https://github.com/kingsznhone/ntqq_msg_db_util.git
cd ntqq_msg_db_util

# 2. 创建虚拟环境并安装依赖（uv 自动选用 Python 3.14）
uv sync

# 3. 激活虚拟环境（可选，也可直接用 uv run）
.venv\Scripts\Activate.ps1
```

### 依赖说明

| 包 | 用途 |
|----|------|
| `sqlcipher3` | SQLCipher 4 解密 |
| `protobuf` | 解析消息体中的 Protobuf blob |
| `python-dotenv` | 从 `.env` 文件读取配置（可选） |
| `bbpb` | Protobuf 辅助工具 |

`3.convert.py` 不依赖 `sqlcipher3`，直接操作明文 SQLite。
