"""将 group_msg_table 行转换为导出库 group_messages 记录。"""

from __future__ import annotations

import json
import sqlite3

from google.protobuf.json_format import MessageToDict

from msgdb.proto.c2c_40800_parser import parse_40800
from .models import GroupMessage


SELECT_SQL = """\
SELECT
    "40001" AS msg_id,
    "40050" AS timestamp,
    "40013" AS direction,
    "40020" AS sender_uid,
    "40033" AS sender_qq,
    "40021" AS group_id,
    "40030" AS group_qq,
    "40011" AS msg_type,
    "40012" AS subtype,
    "40800" AS blob
FROM group_msg_table
ORDER BY "40001"
"""

SELECT_COUNT_SQL = "SELECT COUNT(*) FROM group_msg_table"


def _text(contents) -> str | None:
    parts = [item.text for item in contents if item.text]
    return "\n".join(parts) if parts else None


def _content(result) -> str | None:
    if result.status.value == "null":
        return None
    if result.status.value == "typed":
        segments = [
            MessageToDict(item, preserving_proto_field_name=True)
            for item in result.contents
        ]
    else:
        segments = [
            {
                "number": item.number,
                "wire_type": item.wire_type,
                "raw_value_hex": item.raw_value.hex(),
                "value": (
                    item.value.hex()
                    if isinstance(item.value, bytes)
                    else item.value
                ),
            }
            for item in result.wire_fields
        ]
    return json.dumps(
        {"type": "msg_body", "segments": segments},
        ensure_ascii=False,
    )


def parse_row(row: sqlite3.Row) -> dict:
    """将群消息源表的一行转为 group_messages 可插入的字典。"""
    result = parse_40800(row["blob"])
    contents = result.contents
    first = contents[0] if contents else None
    return {
        "msg_id": row["msg_id"] or 0,
        "timestamp": row["timestamp"] or 0,
        "direction": row["direction"] or 0,
        "sender_uid": row["sender_uid"] or "",
        "sender_qq": row["sender_qq"] or None,
        "group_id": row["group_id"] or "",
        "group_qq": row["group_qq"] or 0,
        "msg_type": row["msg_type"] or 0,
        "subtype": row["subtype"] or None,
        "content_type": first.content_type if first and first.content_type else None,
        "text": _text(contents),
        "parse_status": result.status.value,
        "content": _content(result),
    }


def parse_message(row: sqlite3.Row) -> GroupMessage:
    """将群消息源表的一行解析为 group 表模型。"""
    return GroupMessage(
        msg_id=row["msg_id"] or 0,
        timestamp=row["timestamp"] or 0,
        direction=row["direction"] or 0,
        sender_uid=row["sender_uid"] or "",
        sender_qq=row["sender_qq"] or None,
        group_id=row["group_id"] or "",
        group_qq=row["group_qq"] or 0,
        msg_type=row["msg_type"] or 0,
        subtype=row["subtype"] or None,
        content=parse_40800(row["blob"]),
    )
