# 灵魂提取器：NTQQ 聊天数据库解密、研究与转换工具

一张通往赛博永生的车票。


## 背景

NTQQ（QQ NT 架构）将聊天记录存储在 SQLCipher 4 加密的 SQLite 数据库中（通常命名为 `nt_msg.db`）。文件开头有一段 **1024 字节的自定义头部**，其后才是标准的 SQLCipher 数据库内容。在解密之前必须先剥掉这段头部。

本项目目前以 Windows 为主要运行和研究平台，使用个人长期 QQ 聊天数据库作为样本

密钥为 16 字节 ASCII 字符串，可通过内存调试等方式从 NTQQ 进程中提取。建议使用 PowerShell 脚本提取密钥，2026 年 7 月 21 日验证有效。

https://qqbackup.github.io/QQDecrypt/

## 当前状态

| 部分 | 状态 | 当前说明 |
|------|------|---------|
| 解密 | 可用 | 支持剥离 1024 字节头部、SQLCipher 4 参数验证、逐表导出和损坏页跳过 |
| 精简库 | 可用 | 新建 SQLCipher 库并跳过 `group_msg_table` 数据，再拼接原始头部 |
| 结构化导出 | 可用 | 将 C2C 与 group 主消息表导出为 SQLite，并建立索引和 FTS5 |
| `40800` 解析 | 已接入 | C2C/group 共用 `MsgBody -> repeated MsgContent`；支持强类型解析和 wire fallback |
| 其他 Protobuf | 已建模，待进一步接入 | `40600`、`40605`、`40801`、`40900` 已有独立 schema/parser，当前 `3.export.py` 尚未将它们导出到结构化目标表 |
| 字段研究 | 持续进行 | 已完成大量主表字段、消息体字段和 group 专用字段的样本验证，仍有一批字段只有行为级结论 |

## 字段分析文档

- C2C 字段总览：[db_docs/c2c_msg_table/summary.md](db_docs/c2c_msg_table/summary.md)
- group 字段总览：[db_docs/group_msg_table/summary.md](db_docs/group_msg_table/summary.md)
- C2C 字段报告目录：[db_docs/c2c_msg_table/](db_docs/c2c_msg_table/)
- group 字段报告目录：[db_docs/group_msg_table/](db_docs/group_msg_table/)

### 研究基线与进度

当前文档基于以下数据库快照：

- `c2c_msg_table`：`1,318,588` 行，已有 `23` 个独立字段报告；
- `group_msg_table`：`540,018` 行，已有 `28` 个独立字段报告；
- 两张表的 `40800` 均已确认使用共享的 `MsgBody.content` repeated Protobuf 结构；
- C2C `40800`：非 NULL 数据约 `99.96%`，已区分单段、多段消息及少量旧 wire 形态；
- group `40800`：非 NULL 数据强类型解析成功率为 `100%`，最多观察到 `121` 个消息段；
- 外部资料中出现的 `48000` 已通过全量 wire 扫描排除，当前 canonical 编号为 `40800`。

文档中的置信度含义为：✅ 已验证，🔍 当前样本支持的解释，❓ 仅确认结构或样本不足，未知表示尚无可靠语义。研究结论优先描述可复现的数据行为，不强行套用未经样本验证的产品内部命名。

### 研究重点

- 主表字段：消息 ID、方向、发送者、会话对象、时间、消息类型和 group 会话分区等；
- `40800`：文本、图片、视频、文件、表情、引用、合并转发、系统通知和通话等消息内容；
- group 专用字段：`40600`、`40605`、`40801`、`40900` 的结构已逆向建模，业务语义仍按各字段报告中的置信度使用；
- 未知字段：保留字段号、wire 类型和原始 bytes，避免把多态或新版本字段误判为固定类型。

---

## 文件说明

| 文件 | 用途 |
|------|------|
| `nt_msg.db` | 原始输入，含 1024 字节 NTQQ 自定义头 |
| `nt_msg_clear.db` | 剥头后的 SQLCipher 文件（中间产物） |
| `nt_msg_plain.db` | **最终明文 SQLite**，可直接用任意 SQLite 工具打开 |
| `nt_msg_slim.db` | 以相同密钥重新加密、清空了 `group_msg_table`、并在头部拼接原始 1024 字节头的精简版（SQLCipher 格式，可直接回传 NTQQ） |
| `nt_msg_export.db` | **结构化导出库**，由 `3.export.py` 生成，包含 C2C 与 group 两张消息表，支持全文搜索 |

---

## 脚本一：`1.decrypt.py` — 解密并导出明文数据库

### 当前实现

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

### 结果与限制

- 生成 `nt_msg_clear.db`（中间产物，可删）
- 生成 `nt_msg_plain.db`：**完整明文 SQLite**，无需密钥即可直接用 DB Browser、DBeaver 等工具打开
- 已损坏的页会被自动跳过，损坏行会计入终端统计；输出库支持断点续跑，但不能恢复被跳过的损坏数据

---

## 脚本二：`2.slim.py` — 生成去除 group_msg_table 的精简版

### 背景

`group_msg_table` 储存群聊消息，数据量可达数 GB，且在旧备份中极易出现页损坏（无法直接 `DELETE`），在消息管理器中删除所有群聊消息也不会缩小nt_msg.db的大小。该脚本绕开损坏，生成一个去掉群消息但保留全部其他数据的精简版数据库，仍以 SQLCipher 格式封装（方便回传给 NTQQ 使用）。

### 当前实现

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

### 结果与限制

- 生成 `nt_msg_slim.db`：SQLCipher 格式，带原始 1024 字节头，`group_msg_table` 为空，其余数据完整
- **`group_msg_table` 的所有消息将不存在于输出文件中**，无法恢复（源库 `nt_msg_clear.db` 不受影响）
- 文件体积比原始 `nt_msg.db` 大幅缩小
- 该脚本只处理数据库层复制；不会把已在源库中损坏或无法读取的内容恢复出来

---

## 脚本三：`3.export.py` — 导出结构化消息数据库

### 背景

`nt_msg_plain.db` 中的消息内容（`c2c_msg_table.40800` 和 `group_msg_table.40800` 列）以 Protobuf 编码存储，且夹杂大量未知字段。该脚本解析 Protobuf，提取关键字段，输出一个结构清晰、可直接查询的 SQLite 数据库 `nt_msg_export.db`。

### 当前实现

1. **只读**打开 `nt_msg_plain.db`，分别按 `40001`（消息 ID）顺序扫描 `c2c_msg_table` 和 `group_msg_table`。
2. 用 `msgdb/proto/c2c_40800_parser.py` 解析两张表共用的 `40800` Protobuf blob；该入口在强类型解析失败时保留 wire 字段。
3. C2C 消息写入 `c2c_messages`，群消息写入 `group_messages`；群消息保留 `group_id/group_qq`、`subtype` 和 `parse_status`，并将共享 `MsgContent` 完整 JSON 写入 `content`。
4. 批量写入（默认 2000 行/事务），写入期间暂停两张表的 FTS5 触发器，全部完成后一次性重建索引。

### 输出表结构（`c2c_messages`）

| 列 | 来源字段 | 说明 |
|----|---------|------|
| `msg_id` | `40001` | 消息唯一 ID，同时作为 `c2c_messages` 主键 |
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
| `content` | `40800` 解析 | JSON，含 `type` 鉴别字段，结构按消息类型而异；无法强类型解析时 C2C 保留为空 |

`content` JSON 示例：

```json
{"type": "text",  "text": "你好"}
{"type": "image", "filename": "xxx.jpg", "width": 1080, "height": 720, "filesize": 204800, "md5_hex": "...", "cdn_url": "..."}
{"type": "file",  "filename": "report.pdf", "filesize": 1048576, "md5_hex": "...", "ext": ".pdf"}
{"type": "call",  "call_type": 7, "duration": 61, "desc": "通话时长 00:01"}
{"type": "mixed", "segments": [...]}
```

支持的 `type` 值：`text` / `image` / `video` / `file` / `sticker` / `contact` / `reply` / `forward` / `legacy_forward` / `call` / `sys` / `mixed`

### 输出表结构（`group_messages`）

| 列 | 来源字段 | 说明 |
|----|---------|------|
| `msg_id` | `40001` | 群消息唯一 ID，同时作为 `group_messages` 主键 |
| `timestamp` | `40050` | Unix 秒级时间戳 |
| `direction` | `40013` | 消息来源/方向标志 |
| `sender_uid` | `40020` | 发送者 NT UID |
| `sender_qq` | `40033` | 发送者 QQ 号 |
| `group_id` | `40021` | 群聊对象 ID（十进制群号字符串） |
| `group_qq` | `40030` | 群号数值 |
| `msg_type` | `40011` | 消息外层类型 |
| `subtype` | `40012` | 消息子类型/属性组合 |
| `content_type` | `40800` → `45002` | 首段内容类型 |
| `text` | `40800` → `45101` | 合并后的文本，供全文搜索 |
| `parse_status` | `40800` 解析 | `null` / `typed` / `wire_fallback` |
| `content` | `40800` 解析 | 完整 `MsgContent` JSON；未知结构保留字段号、wire 类型和原始值 |

群聊全文索引为 `group_messages_fts`，其外部内容行号使用 `group_messages.msg_id`；C2C 全文索引为 `c2c_messages_fts`。

### 使用

```bash
uv run python 3.export.py                          # 使用默认路径
uv run python 3.export.py --src nt_msg_plain.db --dst nt_msg_export.db --batch 5000
uv run python 3.export.py --debug                  # 显示逐行解析错误详情
```

### 结果与限制

- 生成 `nt_msg_export.db`：标准 SQLite，无需密钥，可直接用 DB Browser 等工具打开
- 自动建立时间、会话、消息类型索引及 FTS5 全文搜索虚拟表（`c2c_messages_fts`、`group_messages_fts`）
- C2C 与 group 共约 `1,858,606` 行（按当前研究快照）；
- group 的 `parse_status` 为 `null`、`typed`、`wire_fallback` 或 `invalid`，未知 wire 字段不会静默丢弃；
- C2C 当前结构化模型只写入成功解析的 `40800` 内容，解析失败时保留表级元数据，`content`、`text` 等内容字段为空；
- `3.export.py` 当前只导出两张主消息表及 `40800` 内容，尚未把 `40600`、`40605`、`40801`、`40900` 等附加列写入结构化目标库；
- 单行转换异常会单独计入错误计数并跳过，不会中断整个导出。

### 解析代码入口

- 表级适配：`msgdb/c2c/`、`msgdb/group/`；
- 共享消息体：`msgdb/proto/c2c_40800.proto` 与 `msgdb/proto/c2c_40800_parser.py`；
- group 附加结构：`msgdb/proto/group_40600_parser.py`、`group_40605_parser.py`、`group_40801_parser.py`、`group_40900_parser.py`；
- 未知字段保留：`msgdb/proto/wire.py`；
- 协议和解析说明：[msgdb/proto/README.md](msgdb/proto/README.md)。

---

## 环境配置

### 前置要求

- **Python 3.14**（当前项目要求；`pyproject.toml` 中声明 `requires-python = ">=3.14"`）
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

`3.export.py` 不依赖 `sqlcipher3`，直接操作明文 SQLite；完整安装仍建议执行 `uv sync`，因为项目依赖按统一环境声明。

## 使用边界

- 本项目面向本人拥有或获授权处理的数据库，仅用于数据恢复、格式转换和协议研究；
- 密钥、数据库文件、QQ 号、NT UID、昵称和聊天内容均属于敏感数据，请勿提交到公开仓库；
- 运行 `2.slim.py` 前请确认已备份原始库；输出库会永久移除 `group_msg_table` 中的消息；
- 字段报告中的统计数字对应研究快照，换用其他 NTQQ 版本或数据库后应重新验证，不应直接依赖未标记为已验证的语义。
