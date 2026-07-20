# msgdb 解析套件

`msgdb` 按源数据库表划分为两个独立子包：

- `msgdb.c2c`：负责 `c2c_msg_table`，包含 `models.py` 和 `parser.py`，由 `3.export.py` 使用；
- `msgdb.group`：负责 `group_msg_table`，包含 `models.py` 和 `exporter.py`。

## 唯一协议入口

`msgdb/proto/` 是 Protobuf 定义和解析目录：

- `c2c_40800.proto` / `c2c_40800_pb2.py` / `c2c_40800_parser.py`：C2C 与 group 共用的消息体；
- `group_40600.proto` / `group_40600_pb2.py` / `group_40600_parser.py`：group 状态附加字段；
- `group_40605.proto` / `group_40605_pb2.py` / `group_40605_parser.py`：group 空附加字段；
- `group_40801.proto` / `group_40801_pb2.py` / `group_40801_parser.py`：group 摘要/状态快照；
- `group_40900.proto` / `group_40900_pb2.py` / `group_40900_parser.py`：group 引用/转发缓存；
- `wire.py`：统一 wire fallback。

`msgdb/c2c/` 和 `msgdb/group/` 只保留表级字段、模型和导出适配；协议定义和字段 parser 统一放在这里。

## group 解析状态

`msgdb.c2c.parser` 和 `msgdb.group.exporter` 都通过 `msgdb.proto.c2c_40800_parser.parse_40800` 读取 40800；解析失败时由 `msgdb.proto.wire` 保留字段号、wire 类型和原始 payload。
