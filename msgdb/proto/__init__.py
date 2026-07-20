"""NTQQ 消息 BLOB 的按字段编号协议定义入口。"""

from . import c2c_40800_pb2 as msg_40800
from .c2c_40800_parser import parse_40800
from .group_40600_parser import parse_40600
from .group_40605_parser import parse_40605
from .group_40801_parser import parse_40801
from .group_40900_parser import parse_40900

__all__ = ["msg_40800", "parse_40600", "parse_40605", "parse_40800", "parse_40801", "parse_40900"]
