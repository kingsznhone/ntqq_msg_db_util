"""group_msg_table 的导出数据模型。"""

from __future__ import annotations

from dataclasses import dataclass

from msgdb.proto.c2c_40800_parser import Parsed40800


@dataclass(frozen=True)
class GroupMessage:
    """一条群消息的表级元数据和 40800 解析结果。"""

    msg_id: int
    timestamp: int
    direction: int
    sender_uid: str
    sender_qq: int | None
    group_id: str
    group_qq: int
    msg_type: int
    subtype: int | None
    content: Parsed40800
