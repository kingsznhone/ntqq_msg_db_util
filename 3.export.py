#!/usr/bin/env python3
"""
export.py — 将 nt_msg_plain.db 转换为 nt_msg_export.db

用法：
    uv run python 3.export.py
    uv run python 3.export.py --src nt_msg_plain.db --dst nt_msg_export.db
    uv run python 3.export.py --batch 5000

性能说明：
    FTS5 触发器会在每行写入时同步更新索引，开销显著。
    本脚本在批量写入前暂时移除触发器，写入完成后一次性重建 FTS 索引，
    以获得最佳吞吐量。
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time

from msgdb.c2c import parser as c2c_parser
from msgdb.export_schema import (
    drop_fts_triggers,
    init_db,
    insert_group_messages_batch,
    insert_messages_batch,
    rebuild_fts,
    create_indexes,
)
from msgdb.group import exporter as group_exporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# 进度日志每隔多少行打印一次
_LOG_INTERVAL = 50_000


def export_database(src_path: str, dst_path: str, batch_size: int) -> None:
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.execute("PRAGMA synchronous=NORMAL")
    dst.execute("PRAGMA cache_size=-65536")  # 64 MB page cache

    # 初始化 schema（幂等），再摘掉 FTS 触发器供批量写入使用
    init_db(dst)
    drop_fts_triggers(dst)

    c2c_total = src.execute(c2c_parser.SELECT_COUNT_SQL).fetchone()[0]
    group_total = src.execute(group_exporter.SELECT_COUNT_SQL).fetchone()[0]
    total = c2c_total + group_total
    log.info(
        "源库：%s  C2C %d 行，group %d 行，共 %d 行",
        src_path,
        c2c_total,
        group_total,
        total,
    )
    log.info("目标库：%s", dst_path)

    processed = 0
    errors = 0
    t0 = time.monotonic()
    t_last = t0
    c2c_batch: list[dict] = []
    group_batch: list[dict] = []

    def _flush() -> None:
        nonlocal processed
        with dst:
            if c2c_batch:
                insert_messages_batch(dst, c2c_batch)
            if group_batch:
                insert_group_messages_batch(dst, group_batch)
        processed += len(c2c_batch) + len(group_batch)
        c2c_batch.clear()
        group_batch.clear()

    def _export_table(select_sql, parser, target_batch: list[dict]) -> None:
        nonlocal errors, t_last
        for raw in src.execute(select_sql):
            try:
                value = parser(raw)
                target_batch.append(
                    value.to_db_row() if hasattr(value, "to_db_row") else value
                )
            except Exception as exc:
                errors += 1
                log.debug("msg_id=%s 转换失败: %s", raw["msg_id"], exc)

            if len(c2c_batch) + len(group_batch) >= batch_size:
                _flush()

                if processed % _LOG_INTERVAL == 0 or processed == total:
                    now = time.monotonic()
                    elapsed = now - t0
                    speed = processed / elapsed if elapsed > 0 else 0
                    pct = processed * 100 // total if total else 100
                    log.info(
                        "[%3d%%] %9d / %d  %.0f 行/s  错误 %d",
                        pct,
                        processed,
                        total,
                        speed,
                        errors,
                    )
                    t_last = now

    _export_table(c2c_parser.SELECT_SQL, c2c_parser.parse_row, c2c_batch)
    _export_table(group_exporter.SELECT_SQL, group_exporter.parse_row, group_batch)

    _flush()

    elapsed = time.monotonic() - t0
    log.info(
        "主表写入完成：%d 行，错误 %d 行，耗时 %.1f 秒", processed, errors, elapsed
    )

    log.info("建立二级索引…")
    create_indexes(dst)
    log.info("索引建立完成，总耗时 %.1f 秒", time.monotonic() - t0)

    log.info("重建 FTS 索引（c2c_messages_fts、group_messages_fts）…")
    rebuild_fts(dst)
    log.info("FTS 重建完成。总耗时 %.1f 秒", time.monotonic() - t0)

    src.close()
    dst.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="NTQQ 消息库导出：nt_msg_plain.db → nt_msg_export.db"
    )
    ap.add_argument(
        "--src",
        default="nt_msg_plain.db",
        metavar="PATH",
        help="明文源数据库（默认：nt_msg_plain.db）",
    )
    ap.add_argument(
        "--dst",
        default="nt_msg_export.db",
        metavar="PATH",
        help="输出数据库（默认：nt_msg_export.db）",
    )
    ap.add_argument(
        "--batch",
        type=int,
        default=2000,
        metavar="N",
        help="每个事务写入的行数（默认：2000）",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="输出逐行解析错误详情",
    )
    args = ap.parse_args()

    if args.debug:
        logging.getLogger("msgdb.proto").setLevel(logging.DEBUG)

    export_database(args.src, args.dst, args.batch)


if __name__ == "__main__":
    main()
