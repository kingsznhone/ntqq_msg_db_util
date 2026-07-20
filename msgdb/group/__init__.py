"""group_msg_table 表级模型和导出适配。"""

from .exporter import parse_message, parse_row
from .models import GroupMessage

__all__ = ["GroupMessage", "parse_message", "parse_row"]
