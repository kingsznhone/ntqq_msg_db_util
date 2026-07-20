"""无损 Protobuf wire 解析。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WireField:
    """一个 Protobuf 字段的原始 wire 表示。"""

    number: int
    wire_type: int
    raw_value: bytes
    value: int | bytes | None


def read_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    return None


def parse_wire(data: bytes) -> list[WireField]:
    """解析常见 wire 类型，遇到损坏数据抛出 ValueError。"""
    fields: list[WireField] = []
    offset = 0
    while offset < len(data):
        key_start = offset
        item = read_varint(data, offset)
        if item is None:
            raise ValueError(f"invalid field key at offset {key_start}")
        key, offset = item
        number, wire_type = key >> 3, key & 7
        if number <= 0:
            raise ValueError(f"invalid field number {number}")
        value_start = offset
        if wire_type == 0:
            item = read_varint(data, offset)
            if item is None:
                raise ValueError(f"invalid varint at offset {offset}")
            value, offset = item
            fields.append(WireField(number, wire_type, data[value_start:offset], value))
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError(f"truncated fixed64 at offset {offset}")
            fields.append(WireField(number, wire_type, data[offset:end], data[offset:end]))
            offset = end
        elif wire_type == 2:
            item = read_varint(data, offset)
            if item is None:
                raise ValueError(f"invalid length at offset {offset}")
            length, offset = item
            end = offset + length
            if end > len(data):
                raise ValueError(f"truncated length-delimited field at offset {offset}")
            fields.append(WireField(number, wire_type, data[offset:end], data[offset:end]))
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError(f"truncated fixed32 at offset {offset}")
            fields.append(WireField(number, wire_type, data[offset:end], data[offset:end]))
            offset = end
        else:
            raise ValueError(f"unsupported wire type {wire_type} at offset {value_start}")
    return fields
