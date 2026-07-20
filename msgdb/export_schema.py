"""结构化导出数据库的 schema 定义与批量写入函数。"""

from __future__ import annotations

import sqlite3


DDL_C2C_MESSAGES = """\
CREATE TABLE IF NOT EXISTS c2c_messages (
    msg_id       INTEGER PRIMARY KEY,
    timestamp    INTEGER NOT NULL,
    direction    INTEGER NOT NULL,
    sender_uid   TEXT    NOT NULL,
    sender_qq    INTEGER,
    peer_uid     TEXT    NOT NULL,
    peer_qq      INTEGER NOT NULL,
    msg_type     INTEGER NOT NULL,
    content_type INTEGER,
    proto_ver    TEXT,
    inner_ts     INTEGER,
    text         TEXT,
    content      TEXT
);"""

DDL_GROUP_MESSAGES = """\
CREATE TABLE IF NOT EXISTS group_messages (
    msg_id       INTEGER PRIMARY KEY,
    timestamp    INTEGER NOT NULL,
    direction    INTEGER NOT NULL,
    sender_uid   TEXT    NOT NULL,
    sender_qq    INTEGER,
    group_id     TEXT    NOT NULL,
    group_qq     INTEGER NOT NULL,
    msg_type     INTEGER NOT NULL,
    subtype      INTEGER,
    content_type INTEGER,
    text         TEXT,
    parse_status TEXT    NOT NULL,
    content      TEXT
);"""

DDL_C2C_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_c2c_msg_ts ON c2c_messages(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_c2c_msg_peer ON c2c_messages(peer_uid, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_c2c_msg_peer_qq ON c2c_messages(peer_qq, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_c2c_msg_type ON c2c_messages(msg_type, content_type);",
    "CREATE INDEX IF NOT EXISTS idx_c2c_msg_id ON c2c_messages(msg_id);",
)

DDL_GROUP_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_group_ts ON group_messages(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_group_group ON group_messages(group_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_group_group_qq ON group_messages(group_qq, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_group_sender ON group_messages(sender_qq, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_group_type ON group_messages(msg_type, content_type);",
    "CREATE INDEX IF NOT EXISTS idx_group_msg_id ON group_messages(msg_id);",
)

DDL_FTS = {
    "c2c_messages": """\
CREATE VIRTUAL TABLE IF NOT EXISTS c2c_messages_fts USING fts5(
    text, content='c2c_messages', content_rowid='msg_id', tokenize='unicode61'
);""",
    "group_messages": """\
CREATE VIRTUAL TABLE IF NOT EXISTS group_messages_fts USING fts5(
    text, content='group_messages', content_rowid='msg_id', tokenize='unicode61'
);""",
}

DDL_FTS_TRIGGERS = {
    "c2c_messages": (
    """CREATE TRIGGER IF NOT EXISTS c2c_fts_ai AFTER INSERT ON c2c_messages BEGIN
INSERT INTO c2c_messages_fts(rowid, text) VALUES (new.msg_id, new.text); END;""",
    """CREATE TRIGGER IF NOT EXISTS c2c_fts_ad AFTER DELETE ON c2c_messages BEGIN
INSERT INTO c2c_messages_fts(c2c_messages_fts, rowid, text)
VALUES ('delete', old.msg_id, old.text); END;""",
    """CREATE TRIGGER IF NOT EXISTS c2c_fts_au AFTER UPDATE ON c2c_messages BEGIN
INSERT INTO c2c_messages_fts(c2c_messages_fts, rowid, text)
VALUES ('delete', old.msg_id, old.text);
INSERT INTO c2c_messages_fts(rowid, text) VALUES (new.msg_id, new.text); END;""",
    ),
    "group_messages": (
        """CREATE TRIGGER IF NOT EXISTS group_fts_ai AFTER INSERT ON group_messages BEGIN
INSERT INTO group_messages_fts(rowid, text) VALUES (new.msg_id, new.text); END;""",
        """CREATE TRIGGER IF NOT EXISTS group_fts_ad AFTER DELETE ON group_messages BEGIN
INSERT INTO group_messages_fts(group_messages_fts, rowid, text)
VALUES ('delete', old.msg_id, old.text); END;""",
        """CREATE TRIGGER IF NOT EXISTS group_fts_au AFTER UPDATE ON group_messages BEGIN
INSERT INTO group_messages_fts(group_messages_fts, rowid, text)
VALUES ('delete', old.msg_id, old.text);
INSERT INTO group_messages_fts(rowid, text) VALUES (new.msg_id, new.text); END;""",
    ),
}

_INSERT_C2C_MESSAGES_SQL = """\
INSERT OR REPLACE INTO c2c_messages
(msg_id, timestamp, direction, sender_uid, sender_qq, peer_uid, peer_qq,
 msg_type, content_type, proto_ver, inner_ts, text, content)
VALUES
(:msg_id, :timestamp, :direction, :sender_uid, :sender_qq, :peer_uid, :peer_qq,
 :msg_type, :content_type, :proto_ver, :inner_ts, :text, :content);"""

_INSERT_GROUP_SQL = """\
INSERT OR REPLACE INTO group_messages
(msg_id, timestamp, direction, sender_uid, sender_qq, group_id, group_qq,
 msg_type, subtype, content_type, text, parse_status, content)
VALUES
(:msg_id, :timestamp, :direction, :sender_uid, :sender_qq, :group_id, :group_qq,
 :msg_type, :subtype, :content_type, :text, :parse_status, :content);"""


def init_db(conn: sqlite3.Connection) -> None:
    """创建 C2C 与 group 两张导出主表及其索引/FTS。"""
    with conn:
        conn.execute(DDL_C2C_MESSAGES)
        conn.execute(DDL_GROUP_MESSAGES)
        for ddl in (*DDL_C2C_INDEXES, *DDL_GROUP_INDEXES):
            conn.execute(ddl)
        for ddl in DDL_FTS.values():
            conn.execute(ddl)
        for triggers in DDL_FTS_TRIGGERS.values():
            for ddl in triggers:
                conn.execute(ddl)


def drop_fts_triggers(conn: sqlite3.Connection) -> None:
    """批量写入前移除两张表的 FTS 触发器。"""
    with conn:
        for name in (
            "c2c_fts_ai", "c2c_fts_ad", "c2c_fts_au",
            "group_fts_ai", "group_fts_ad", "group_fts_au",
        ):
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """批量写入结束后重建两张表的 FTS 索引。"""
    with conn:
        conn.execute("INSERT INTO c2c_messages_fts(c2c_messages_fts) VALUES ('rebuild');")
        conn.execute("INSERT INTO group_messages_fts(group_messages_fts) VALUES ('rebuild');")


def insert_messages_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(_INSERT_C2C_MESSAGES_SQL, rows)


def insert_group_messages_batch(conn: sqlite3.Connection, rows: list[dict]) -> None:
    conn.executemany(_INSERT_GROUP_SQL, rows)
