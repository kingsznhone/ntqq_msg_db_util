"""
从 c2c_msg_table 行解析 Message 对象。

外部入口：
    parse_row(row: sqlite3.Row) → Message

源库查询常量：
    SELECT_SQL        — 分页游标查询语句
    SELECT_COUNT_SQL  — 总行数查询
"""

from __future__ import annotations

import json
import logging
import sqlite3

from . import msg_pb2
from .models import (
    CallContent,
    ContactContent,
    FileContent,
    ForwardContent,
    ImageContent,
    LegacyForwardContent,
    Message,
    MixedContent,
    ReplyContent,
    StickerContent,
    SysContent,
    TextContent,
    VideoContent,
    content_to_dict,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 源库查询语句
# ─────────────────────────────────────────────────────────────────────────────

# 只拉取 convert 需要的列，跳过大量未知列和其他 BLOB
SELECT_SQL = """\
SELECT
    "40001" AS id,
    "40050" AS timestamp,
    "40013" AS direction,
    "40020" AS sender_uid,
    "40033" AS sender_qq,
    "40021" AS peer_uid,
    "40030" AS peer_qq,
    "40011" AS msg_type,
    "40800" AS blob
FROM c2c_msg_table
ORDER BY "40001\""""

SELECT_COUNT_SQL = "SELECT COUNT(*) FROM c2c_msg_table"


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────────────────


def _hex(b: bytes) -> str:
    """将 raw binary bytes 转为 hex 字符串；None / 空 bytes 返回空串。"""
    return b.hex() if b else ""


def _first_text(contents: list[msg_pb2.MsgContent]) -> str | None:
    """收集所有 MsgContent 中的文本段，合并后返回；无文本时返回 None。"""
    parts = [c.text for c in contents if c.text]
    return "\n".join(parts) if parts else None


# ── 各类型 Content 构造 ────────────────────────────────────────────────────


def _parse_image(c: msg_pb2.MsgContent) -> ImageContent:
    fallbacks = list(c.text_fallback)
    return ImageContent(
        filename=c.filename or "",
        width=c.img_width,
        height=c.img_height,
        filesize=c.filesize,
        md5_hex=_hex(c.md5_raw),
        cdn_url=c.cdn_url_1 or c.cdn_url_2 or c.cdn_url_3 or "",
        local_path=c.local_path or None,
        text_fallback=fallbacks[0] if fallbacks else None,
    )


def _parse_video(c: msg_pb2.MsgContent) -> VideoContent:
    return VideoContent(
        filename=c.filename or "",
        filesize=c.filesize,
        md5_hex=_hex(c.md5_raw),
        duration=c.f45415 or None,
        cdn_url=c.cdn_url_1 or c.cdn_url_2 or None,
        local_path=c.local_path or None,
    )


def _parse_file(c: msg_pb2.MsgContent) -> FileContent:
    return FileContent(
        filename=c.filename or "",
        filesize=c.filesize,
        md5_hex=_hex(c.md5_raw),
        ext=c.file_ext or "",
        cdn_token=c.cdn_token or None,
        cdn_path=c.cdn_path or None,
    )


def _parse_sticker(c: msg_pb2.MsgContent) -> StickerContent:
    inner = c.sticker.data.data.data
    md5_raw = inner.md5
    md5_str = (
        md5_raw.decode("utf-8", errors="replace")
        if isinstance(md5_raw, bytes)
        else str(md5_raw)
    )
    fallbacks = list(c.text_fallback)
    return StickerContent(
        sticker_id=inner.sticker_id,
        md5=md5_str,
        text_fallback=fallbacks[0] if fallbacks else None,
    )


def _parse_contact(c: msg_pb2.MsgContent) -> ContactContent:
    return ContactContent(
        uid=c.nc_uid_1 or "",
        nickname=c.nc_nickname_1 or c.nc_nickname_2 or "",
        remark=c.nc_remark_1 or c.nc_remark_2 or None,
    )


def _parse_reply(c: msg_pb2.MsgContent) -> ReplyContent:
    return ReplyContent(
        ref_uid=c.nc_uid_1 or "",
        ref_nickname=c.nc_nickname_1 or c.nc_nickname_2 or "",
        ref_remark=c.nc_remark_1 or c.nc_remark_2 or None,
        ref_summary=c.ref_f47713 or None,
        text=c.text or None,
    )


def _parse_legacy_forward(c: msg_pb2.MsgContent) -> LegacyForwardContent:
    return LegacyForwardContent(
        resid=c.legacy_fwd_resid or None,
        uuid=c.legacy_fwd_uuid or None,
        xml=c.legacy_fwd_xml or None,
    )


# ── msg_type=2 多段解析 ─────────────────────────────────────────────────────


def _segment_from(c: msg_pb2.MsgContent) -> dict | None:
    """将单个 MsgContent 转为 content dict，用作 MixedContent.segments 的一项。"""
    ct = c.content_type
    if ct == 1 and c.text:
        return content_to_dict(TextContent(text=c.text))
    if ct == 2:
        if c.img_width > 0:
            return content_to_dict(_parse_image(c))
        if c.f45415 > 0 or c.vid_f47601 > 0:
            return content_to_dict(_parse_video(c))
        if c.text:
            return content_to_dict(TextContent(text=c.text))
    if ct == 5 or c.sticker.data.data.data.sticker_id != 0:
        return content_to_dict(_parse_sticker(c))
    if ct == 9:
        return content_to_dict(_parse_video(c))
    # 有文本则保底返回文本段
    if c.text:
        return content_to_dict(TextContent(text=c.text))
    return None


def _parse_msg_type2(
    contents: list[msg_pb2.MsgContent],
) -> (
    TextContent
    | ImageContent
    | VideoContent
    | StickerContent
    | LegacyForwardContent
    | MixedContent
):
    """
    解析 msg_type=2（标准消息）。

    单段：按 content_type 直接返回对应 Content。
    多段：返回 MixedContent，segments 列表包含每段的序列化 dict。
    """
    if len(contents) == 1:
        c = contents[0]
        ct = c.content_type
        if ct == 1:
            return TextContent(text=c.text)
        if ct == 2:
            if c.img_width > 0:
                return _parse_image(c)
            if c.f45415 > 0 or c.vid_f47601 > 0:
                return _parse_video(c)
            # content_type=2 但既无图片尺寸也无视频时长 → 保底文本
            return TextContent(text=c.text or "")
        if ct == 5 or c.sticker.data.data.data.sticker_id != 0:
            return _parse_sticker(c)
        if ct == 9:
            return _parse_video(c)
        if ct == 16:
            return _parse_legacy_forward(c)
        # 未知子类型：保底文本
        return TextContent(text=c.text or "")

    # 多段消息 → MixedContent
    segments = [seg for c in contents if (seg := _segment_from(c)) is not None]
    return MixedContent(segments=segments)


# ── 顶层分发 ───────────────────────────────────────────────────────────────


def _parse_content(
    msg_type: int,
    contents: list[msg_pb2.MsgContent],
) -> (
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
    | None
):
    if not contents:
        return None
    c = contents[0]

    if msg_type == 2:
        return _parse_msg_type2(contents)

    if msg_type == 3:
        return _parse_file(c)

    if msg_type == 5:
        # 引用回复（有 ref_msg）vs 名片分享（仅 nc_uid_1）
        if c.ref_msg.content_type:
            return _parse_reply(c)
        if c.nc_uid_1:
            return _parse_contact(c)
        return _parse_reply(c)

    if msg_type == 6:
        return _parse_contact(c)

    if msg_type == 7:
        # 带位置 tag 的短视频
        return _parse_video(c)

    if msg_type == 8:
        return _parse_legacy_forward(c)

    if msg_type == 11:
        meta_raw = c.fwd_meta
        try:
            meta: dict = json.loads(meta_raw) if meta_raw else {}
        except json.JSONDecodeError:
            meta = {"raw": meta_raw}
        return ForwardContent(
            meta=meta,
            uuid=c.fwd_uuid or None,
            token=c.fwd_token or None,
        )

    if msg_type == 17:
        return SysContent(
            sub_type=c.sys_f80810 or None,
            content=c.sys_content or None,
        )

    if msg_type == 19:
        return CallContent(
            call_type=c.call_f48151,
            duration=c.call_f48152,
            desc=c.call_desc or "",
        )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 公共入口
# ─────────────────────────────────────────────────────────────────────────────


def parse_row(row: sqlite3.Row) -> Message:
    """
    将 c2c_msg_table 的一行解析为 Message。

    40800 为 NULL 或 protobuf 解析失败时，content / text 等字段为 None，
    其余元数据字段照常填充，不会抛出异常。
    """
    rowid = row["id"]
    msg_id = row["id"] or 0
    timestamp = row["timestamp"] or 0
    direction = row["direction"] or 0
    sender_uid = row["sender_uid"] or ""
    sender_qq = row["sender_qq"] or None
    peer_uid = row["peer_uid"] or ""
    peer_qq = row["peer_qq"] or 0
    msg_type = row["msg_type"] or 0
    blob = row["blob"]

    content_type: int | None = None
    proto_ver: str | None = None
    inner_ts: int | None = None
    text: str | None = None
    content = None

    if blob:
        try:
            body = msg_pb2.MsgBody()
            body.ParseFromString(blob)
            contents = list(body.content)
            if contents:
                first = contents[0]
                content_type = first.content_type or None
                proto_ver = first.ext_proto_ver or None
                inner_ts = first.ext_timestamp or None
                text = _first_text(contents)
                content = _parse_content(msg_type, contents)
        except Exception as exc:
            log.debug("id=%d parse error: %s", rowid, exc)

    return Message(
        id=rowid,
        msg_id=msg_id,
        timestamp=timestamp,
        direction=direction,
        sender_uid=sender_uid,
        sender_qq=sender_qq,
        peer_uid=peer_uid,
        peer_qq=peer_qq,
        msg_type=msg_type,
        content_type=content_type,
        proto_ver=proto_ver,
        inner_ts=inner_ts,
        text=text,
        content=content,
    )
