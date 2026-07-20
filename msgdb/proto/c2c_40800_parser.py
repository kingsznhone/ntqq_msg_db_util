"""C2C 与 group 共用的 40800 Protobuf 解析入口。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import c2c_40800_pb2 as pb
from .wire import WireField, parse_wire


class ParseStatus(StrEnum):
    NULL = "null"
    TYPED = "typed"
    WIRE_FALLBACK = "wire_fallback"
    INVALID = "invalid"


@dataclass(frozen=True)
class Parsed40800:
    status: ParseStatus
    contents: tuple[object, ...] = ()
    wire_fields: tuple[WireField, ...] = ()
    error: str | None = None


def parse_40800(blob: bytes | None) -> Parsed40800:
    """解析 40800；失败时保留原始 wire 字段。"""
    if not blob:
        return Parsed40800(ParseStatus.NULL)
    try:
        body = pb.MsgBody()
        body.ParseFromString(blob)
        return Parsed40800(ParseStatus.TYPED, tuple(body.content))
    except Exception as exc:
        try:
            fields = tuple(parse_wire(blob))
        except ValueError as wire_exc:
            return Parsed40800(
                ParseStatus.INVALID,
                error=f"protobuf={type(exc).__name__}; wire={wire_exc}",
            )
        return Parsed40800(
            ParseStatus.WIRE_FALLBACK,
            wire_fields=fields,
            error=f"protobuf={type(exc).__name__}",
        )
