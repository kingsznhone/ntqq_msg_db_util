# NTQQ Protobuf 定义与解析

本目录按数据库字段拆分协议定义和解析入口；`40800` 是 C2C/group 共用，group 其他字段使用独立 schema。

## 文件

- `c2c_40800.proto`：C2C/group 共用的消息体超集（名称以前缀 `c2c` 表示其定义来源）；
- `group_40600.proto`：group 状态附加字段；
- `group_40605.proto`：group 空附加字段；
- `group_40801.proto`：group 摘要/状态快照；
- `group_40900.proto`：group 引用/转发缓存；
- 对应的 `*_pb2.py`：分别由同名 `.proto` 生成，禁止手工编辑；
- `*_parser.py`：各字段的解析入口；
- `wire.py`：所有 parser 共用的 wire fallback。

## 表级边界

- `msgdb/c2c/` 只处理 C2C 表元数据和导出内容模型；
- `msgdb/group/` 只处理 group 表元数据和导出适配；
- 协议结构按字段文件维护，fallback 逻辑由本目录统一提供。

文件名包含表名前缀，可以直接使用普通 `import` 语法引用对应的 `*_pb2.py` 和 parser。

## 保留的研究结论

- `40800` 是 C2C/group 共用的消息体；`45001` 是段级 ID，不等于外层表的 `40001`；
- `45101` 在 C2C/group 样本中按 UTF-8 应用层文本处理；
- raw hash、CDN 二进制值和未知 length-delimited 字段必须保留为 `bytes`；
- `40600`、`40605`、`40801`、`40900` 使用 group 各自独立 schema，业务语义仍按字段报告中的置信度解释；
- `40900` 中的 `40800/40801/40802/41999` 保留为 `bytes`，避免把多态缓存误判为单一消息类型。
