#!/usr/bin/env python3
"""
convert.py — 将 nt_msg_plain.db 转换为 nt_msg_export.db

用法：
    uv run python convert.py
    uv run python convert.py --src nt_msg_plain.db --dst nt_msg_export.db
    uv run python convert.py --batch 5000

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

from msgdb.parser import SELECT_COUNT_SQL, SELECT_SQL, parse_row
from msgdb.schema import init_db, insert_messages_batch, rebuild_fts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# 进度日志每隔多少行打印一次
_LOG_INTERVAL = 50_000


def _drop_fts_triggers(dst: sqlite3.Connection) -> None:
    """临时移除 FTS5 维护触发器，批量写入期间跳过逐行索引更新。"""
    for name in ("fts_ai", "fts_ad", "fts_au"):
        dst.execute(f"DROP TRIGGER IF EXISTS {name}")


def convert(src_path: str, dst_path: str, batch_size: int) -> None:
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.execute("PRAGMA synchronous=NORMAL")
    dst.execute("PRAGMA cache_size=-65536")   # 64 MB page cache

    # 初始化 schema（幂等），再摘掉 FTS 触发器供批量写入使用
    init_db(dst)
    _drop_fts_triggers(dst)

    total = src.execute(SELECT_COUNT_SQL).fetchone()[0]
    log.info("源库：%s  共 %d 行", src_path, total)
    log.info("目标库：%s", dst_path)

    processed = 0
    errors    = 0
    t0        = time.monotonic()
    t_last    = t0
    batch: list[dict] = []

    def _flush() -> None:
        nonlocal processed
        if not batch:
            return
        with dst:
            insert_messages_batch(dst, batch)
        processed += len(batch)
        batch.clear()

    cursor = src.execute(SELECT_SQL)
    for raw in cursor:
        try:
            msg = parse_row(raw)
            batch.append(msg.to_db_row())
        except Exception as exc:
            errors += 1
            try:
                rid = raw["id"]
            except Exception:
                rid = "?"
            log.debug("id=%s 转换失败: %s", rid, exc)

        if len(batch) >= batch_size:
            _flush()

            if processed % _LOG_INTERVAL == 0 or processed == total:
                now     = time.monotonic()
                elapsed = now - t0
                speed   = processed / elapsed if elapsed > 0 else 0
                pct     = processed * 100 // total
                log.info(
                    "[%3d%%] %9d / %d  %.0f 行/s  错误 %d",
                    pct, processed, total, speed, errors,
                )
                t_last = now

    _flush()

    elapsed = time.monotonic() - t0
    log.info("主表写入完成：%d 行，错误 %d 行，耗时 %.1f 秒", processed, errors, elapsed)

    log.info("重建 FTS 索引（messages_fts）…")
    rebuild_fts(dst)
    log.info("FTS 重建完成。总耗时 %.1f 秒", time.monotonic() - t0)

    src.close()
    dst.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="NTQQ 消息库转换：nt_msg_plain.db → nt_msg_export.db"
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
        logging.getLogger("msgdb.parser").setLevel(logging.DEBUG)

    convert(args.src, args.dst, args.batch)


if __name__ == "__main__":
    main()
