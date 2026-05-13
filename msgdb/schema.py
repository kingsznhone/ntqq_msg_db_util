"""
导出数据库 Schema 定义与初始化。

导出库（nt_msg_export.db）只含一张主表 messages 和配套索引 / FTS5 全文索引。

设计原则：
  - 高频查询字段（timestamp / peer_uid / msg_type）有独立索引
  - text 列挂载 FTS5 虚拟表，支持中文全文搜索（tokenize=unicode61）
  - FTS5 使用 content= 模式（外部内容表），避免数据重复存储
  - 写入后通过触发器自动维护 FTS 索引
"""

import sqlite3


# ─────────────────────────────────────────────────────────────────────────────
# DDL
# ─────────────────────────────────────────────────────────────────────────────

DDL_MESSAGES = """\
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY,
                 -- 原始 c2c_msg_table rowid，保持与源库对应关系

    msg_id       INTEGER NOT NULL,
                 -- 40001：全局唯一消息 ID（单调递增）

    timestamp    INTEGER NOT NULL,
                 -- 40050：Unix 秒，服务端外层时间戳

    direction    INTEGER NOT NULL,
                 -- 40013：1=发出，0=收到

    sender_uid   TEXT    NOT NULL,
                 -- 40020：发送方 NT UID（"u_..." 格式）

    sender_qq    INTEGER,
                 -- 40033：发送者 QQ 号

    peer_uid     TEXT    NOT NULL,
                 -- 40021：会话对象 NT UID（C2C 会话中为对方 UID）

    peer_qq      INTEGER NOT NULL,
                 -- 40030：会话对象 QQ 号（与消息方向无关，始终为对方 QQ）

    msg_type     INTEGER NOT NULL,
                 -- 40011：消息外层类型
                 --   2=文本/媒体  3=文件  5=引用/名片  6=名片
                 --   7=位置短视频 8=旧转发 11=合并转发
                 --   17=系统通知  19=通话

    content_type INTEGER,
                 -- 45002：内容子类型（首段），仅标准消息有效
                 --   1=文本  2=图片/媒体  5=贴图  6=富文本  9=视频  16=旧转发

    proto_ver    TEXT,
                 -- 49154：NT 协议版本标识，"1"（早期）/ "nt_1"（2025-12 起）

    inner_ts     INTEGER,
                 -- 49155：消息内层时间戳（Unix 秒），与 timestamp 偏差通常 <5s

    text         TEXT,
                 -- 所有文本段（45101）合并后的纯文本；非文本类型为 NULL
                 -- 同时作为 messages_fts 的外部内容来源

    content      TEXT
                 -- JSON：类型专有内容，含 "type" 鉴别字段
                 -- 结构见 msgdb/models.py 中各 Content dataclass
);"""

_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_msg_ts      ON messages(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_msg_peer    ON messages(peer_uid, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_msg_peer_qq ON messages(peer_qq, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_msg_type    ON messages(msg_type, content_type);",
    "CREATE INDEX IF NOT EXISTS idx_msg_id      ON messages(msg_id);",
)

# FTS5 外部内容表：不重复存储文本，节省空间；
# tokenize=unicode61 对 CJK 字符按码点分词（逐字匹配）
_DDL_FTS = """\
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
);"""

# 触发器：在 messages 行写入/更新/删除时同步维护 FTS 索引
_DDL_FTS_TRIGGERS = (
    """\
CREATE TRIGGER IF NOT EXISTS fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;""",
    """\
CREATE TRIGGER IF NOT EXISTS fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
END;""",
    """\
CREATE TRIGGER IF NOT EXISTS fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;""",
)


# ─────────────────────────────────────────────────────────────────────────────
# 公共函数
# ─────────────────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    """
    在给定连接上初始化导出数据库 schema。

    幂等：所有语句均使用 IF NOT EXISTS，可安全重复调用。
    调用方负责打开连接并设置 journal_mode / synchronous 等性能参数。
    """
    with conn:
        conn.execute(DDL_MESSAGES)
        for ddl in _DDL_INDEXES:
            conn.execute(ddl)
        conn.execute(_DDL_FTS)
        for ddl in _DDL_FTS_TRIGGERS:
            conn.execute(ddl)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """
    重建 FTS 索引（批量导入完成后调用，比逐行触发更高效）。

    若使用批量导入（executemany + 手动事务），应在导入前禁用触发器或
    导入后调用本函数以确保 FTS 与主表同步。
    """
    with conn:
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild');")


_INSERT_SQL = """\
INSERT OR REPLACE INTO messages
    (id, msg_id, timestamp, direction, sender_uid, sender_qq, peer_uid, peer_qq,
     msg_type, content_type, proto_ver, inner_ts, text, content)
VALUES
    (:id, :msg_id, :timestamp, :direction, :sender_uid, :sender_qq, :peer_uid, :peer_qq,
     :msg_type, :content_type, :proto_ver, :inner_ts, :text, :content);"""


def insert_message(conn: sqlite3.Connection, row: dict) -> None:
    """插入单条消息（row 为 Message.to_db_row() 的返回值）。"""
    conn.execute(_INSERT_SQL, row)


def insert_messages_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """
    批量插入消息（在外部事务内调用，提升写入性能）。

    示例：
        with conn:
            insert_messages_batch(conn, [msg.to_db_row() for msg in batch])
    """
    conn.executemany(_INSERT_SQL, rows)
