"""group_msg_table.40801 的 Protobuf 解析入口。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import group_40801_pb2 as pb
from .wire import WireField, parse_wire


class ParseStatus(StrEnum):
    NULL = "null"
    TYPED = "typed"
    WIRE_FALLBACK = "wire_fallback"
    INVALID = "invalid"


@dataclass(frozen=True)
class Parsed40801:
    status: ParseStatus
    contents: tuple[object, ...] = ()
    wire_fields: tuple[WireField, ...] = ()
    error: str | None = None


def parse_40801(blob: bytes | None) -> Parsed40801:
    if not blob:
        return Parsed40801(ParseStatus.NULL)
    try:
        body = pb.Body()
        body.ParseFromString(blob)
        return Parsed40801(ParseStatus.TYPED, tuple(body.content))
    except Exception as exc:
        try:
            fields = tuple(parse_wire(blob))
        except ValueError as wire_exc:
            return Parsed40801(ParseStatus.INVALID, error=f"protobuf={type(exc).__name__}; wire={wire_exc}")
        return Parsed40801(ParseStatus.WIRE_FALLBACK, wire_fields=fields, error=f"protobuf={type(exc).__name__}")