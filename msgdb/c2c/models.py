"""
消息数据模型。

每种消息类型对应一个 Content dataclass，序列化为 JSON 存入 messages.content 列。
JSON 结构含 "type" 鉴别字段，便于反序列化时按类型还原。

消息类型映射（msg_type = c2c_msg_table.40011）：
  2  → TextContent / ImageContent / VideoContent / StickerContent（按 content_type 细分）
  3  → FileContent
  5  → ReplyContent（引用回复）/ ContactContent（名片分享，附文字时带 text 字段）
  6  → ContactContent
  7  → VideoContent（带位置 tag 的短视频，经纬度全为 0）
  8  → LegacyForwardContent（旧协议合并转发，XML）
  11 → ForwardContent（NT 合并转发，JSON）
  17 → SysContent
  19 → CallContent

多段消息（图文混排）：content = MixedContent，其 segments 为各段 Content dict 列表。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Content dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TextContent:
    """纯文本 (msg_type=2, content_type=1)。"""

    text: str


@dataclass
class ImageContent:
    """图片 (msg_type=2, content_type=2, img_width>0)。"""

    filename: str
    width: int
    height: int
    filesize: int
    md5_hex: str  # 45406 raw binary → hex 字符串
    cdn_url: str  # 45802 主 CDN URL 路径
    local_path: str | None = None  # 45812 本地缓存路径
    text_fallback: str | None = None  # 45815 降级文本（如 "[动画表情]"）


@dataclass
class VideoContent:
    """视频 (msg_type=2/7, 有时长字段)。"""

    filename: str
    filesize: int
    md5_hex: str
    duration: int | None  # 45415
    cdn_url: str | None  # 45802
    local_path: str | None = None


@dataclass
class FileContent:
    """文件附件 (msg_type=3)。"""

    filename: str
    filesize: int
    md5_hex: str
    ext: str  # 45419
    cdn_token: str | None = None  # 45503
    cdn_path: str | None = None  # 45504


@dataclass
class StickerContent:
    """贴图 / 动画表情 (msg_type=2, content_type=5)。"""

    sticker_id: int  # 45600 嵌套字段
    md5: str
    text_fallback: str | None = None


@dataclass
class ContactContent:
    """名片 (msg_type=6)。"""

    uid: str  # 47703
    nickname: str  # 47705
    remark: str | None = None  # 47706


@dataclass
class ReplyContent:
    """引用回复 (msg_type=5)。"""

    ref_uid: str  # 47703 被引用方 UID
    ref_nickname: str  # 47705
    ref_remark: str | None  # 47706
    ref_summary: str | None  # 47713 引用内容文字摘要
    text: str | None = None  # 引用时附带的文字（45101）


@dataclass
class ForwardContent:
    """NT 合并转发 (msg_type=11)。"""

    meta: dict  # 47901 JSON 解析结果
    uuid: str | None  # 47904
    token: str | None = None  # 47902 base64 下载 token


@dataclass
class LegacyForwardContent:
    """旧协议合并转发 XML (msg_type=8)。"""

    resid: str | None  # 48601
    uuid: str | None  # 48603
    xml: str | None  # 48602


@dataclass
class CallContent:
    """通话通知 (msg_type=19)。"""

    call_type: int  # 48151
    duration: int  # 48152
    desc: str  # 48153


@dataclass
class SysContent:
    """系统通知 (msg_type=17)。"""

    sub_type: int | None  # 80810
    content: str | None  # 80900


@dataclass
class MixedContent:
    """多段消息（图文混排，segments ≥ 2）。"""

    segments: list[dict] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Content 类型联合 + 序列化帮助
# ─────────────────────────────────────────────────────────────────────────────

Content = (
    TextContent
    | ImageContent
    | VideoContent
    | FileContent
    | StickerContent
    | ContactContent
    | ReplyContent
    | ForwardContent
    | LegacyForwardContent
    | CallContent
    | SysContent
    | MixedContent
)

# type 鉴别字段与 dataclass 的对应关系
_TYPE_TAG: dict[type, str] = {
    TextContent: "text",
    ImageContent: "image",
    VideoContent: "video",
    FileContent: "file",
    StickerContent: "sticker",
    ContactContent: "contact",
    ReplyContent: "reply",
    ForwardContent: "forward",
    LegacyForwardContent: "legacy_forward",
    CallContent: "call",
    SysContent: "sys",
    MixedContent: "mixed",
}

_TAG_TYPE: dict[str, type] = {v: k for k, v in _TYPE_TAG.items()}


def content_to_dict(c: Content) -> dict:
    """将 Content dataclass 转为含 type 鉴别字段的 dict，供 JSON 序列化。"""
    d = asdict(c)
    d["type"] = _TYPE_TAG[type(c)]
    return d


def content_from_dict(d: dict) -> Content:
    """从 JSON dict 还原 Content dataclass（反序列化）。"""
    tag = d.pop("type")
    cls = _TAG_TYPE[tag]
    return cls(**d)


# ─────────────────────────────────────────────────────────────────────────────
# Message（主记录）
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Message:
    """一条完整消息记录，对应导出库 c2c_messages 表的一行。"""

    msg_id: int  # 40001 消息唯一 ID
    timestamp: int  # 40050 Unix 秒（外层服务端时间）
    direction: int  # 40013：1=发出，0=收到
    sender_uid: str  # 40020 发送方 NT UID
    sender_qq: int | None  # 40033 发送者 QQ 号
    peer_uid: str  # 40021 会话对象 NT UID
    peer_qq: int  # 40030 会话对象 QQ 号
    msg_type: int  # 40011 消息类型
    content_type: int  # 45002 内容子类型（首段）
    proto_ver: str | None  # 49154："1" / "nt_1"
    inner_ts: int | None  # 49155 消息内层时间戳（Unix 秒）
    text: str | None  # 所有文本段合并（供全文搜索；非文本类型为 NULL）
    content: Content | None  # 类型专有内容，序列化后写入 content 列

    def to_db_row(self) -> dict:
        """
        转换为可直接写入 c2c_messages 表的字典。
        content 字段序列化为 JSON 字符串；其余字段类型与列定义对齐。
        """
        return {
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
            "direction": self.direction,
            "sender_uid": self.sender_uid,
            "sender_qq": self.sender_qq,
            "peer_uid": self.peer_uid,
            "peer_qq": self.peer_qq,
            "msg_type": self.msg_type,
            "content_type": self.content_type,
            "proto_ver": self.proto_ver,
            "inner_ts": self.inner_ts,
            "text": self.text,
            "content": (
                json.dumps(content_to_dict(self.content), ensure_ascii=False)
                if self.content is not None
                else None
            ),
        }

    @staticmethod
    def from_db_row(row: dict) -> "Message":
        """从 c2c_messages 表行还原 Message（content 反序列化）。"""
        d = dict(row)
        raw = d.pop("content")
        content = content_from_dict(json.loads(raw)) if raw else None
        return Message(**d, content=content)
