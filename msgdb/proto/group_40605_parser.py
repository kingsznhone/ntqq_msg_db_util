"""group_msg_table.40605 的 Protobuf 解析入口。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import group_40605_pb2 as pb
from .wire import WireField, parse_wire


class ParseStatus(StrEnum):
    NULL = "null"
    TYPED = "typed"
    WIRE_FALLBACK = "wire_fallback"
    INVALID = "invalid"


@dataclass(frozen=True)
class Parsed40605:
    status: ParseStatus
    content: object | None = None
    wire_fields: tuple[WireField, ...] = ()
    error: str | None = None


def parse_40605(blob: bytes | None) -> Parsed40605:
    if not blob:
        return Parsed40605(ParseStatus.NULL)
    try:
        body = pb.Body()
        body.ParseFromString(blob)
        return Parsed40605(ParseStatus.TYPED, body.content)
    except Exception as exc:
        try:
            fields = tuple(parse_wire(blob))
        except ValueError as wire_exc:
            return Parsed40605(
                ParseStatus.INVALID,
                error=f"protobuf={type(exc).__name__}; wire={wire_exc}",
            )
        return Parsed40605(
            ParseStatus.WIRE_FALLBACK,
            wire_fields=fields,
            error=f"protobuf={type(exc).__name__}",
        )
