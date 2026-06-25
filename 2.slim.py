"""
nt_msg_slim.db 生成工具

策略：新建空 SQLCipher 库，逐表复制数据（跳过 group_msg_table 的行），
      绕过源库损坏页的问题，最后重新拼接 1024 字节头部。

流程：
  1. 打开 nt_msg_clear.db（源加密库，只读）
  2. 新建 _slim_work.db（目标加密库，相同参数）
  3. 逐表建 schema：group_msg_table 只建空表，其余表复制所有行
  4. 复制索引定义
  5. 从 nt_msg.db 读取原始 1024 字节头部
  6. 拼接头部 + _slim_work.db → nt_msg_slim.db
  7. 删除 _slim_work.db

依赖：uv add sqlcipher3
"""

import os
import re
import sys
import time
import pathlib

from dotenv import load_dotenv
import sqlcipher3.dbapi2 as sc

load_dotenv()


# ─── 配置（与 main.py 保持一致）───────────────────────────────────────────────
INPUT_DB = "nt_msg.db"  # 含 1024 字节头的原始文件（只用于读取头部）
CLEAR_DB = "nt_msg_clear.db"  # 已剥头的 SQLCipher 源库（只读）
OUTPUT_DB = "nt_msg_slim.db"  # 输出：无 group_msg_table 数据 + 重新加头

DB_KEY = os.getenv("NTQQ_DB_KEY") or ""  # 优先读取环境变量；也可在引号内填写回退密钥

SKIP_TABLE = "group_msg_table"  # 该表只建空表，不复制行
# ─────────────────────────────────────────────────────────────────────────────

HEADER_SIZE = 1024
WORK_DB = "_slim_work.db"
BATCH_SIZE = 5000


def open_enc(path: pathlib.Path):
    conn = sc.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA cipher_page_size = 4096;")
    conn.execute(f"PRAGMA key = '{DB_KEY}';")
    conn.execute("PRAGMA kdf_iter = 4000;")
    conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()
    return conn


def copy_table(
    src: sc.Connection, dst: sc.Connection, table: str, src_path: pathlib.Path
) -> tuple[int, int]:
    """rowid 游标分页，把 src 中的表复制到 dst，遇到损坏自动跳过。"""
    ddl = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    ddl_safe = re.sub(
        r"^CREATE\s+TABLE\s+", "CREATE TABLE IF NOT EXISTS ", ddl, flags=re.IGNORECASE
    )
    dst.execute(ddl_safe)

    ncols = len(src.execute(f'PRAGMA table_info("{table}")').fetchall())
    ph = ",".join("?" * ncols)

    total_src = src.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    ok_rows = 0
    bad_skips = 0
    last_rowid = 0
    batch = BATCH_SIZE
    t0 = time.time()

    # src 连接遇到损坏需要重新打开
    enc = src  # 初始用传入的连接

    while True:
        try:
            rows_with_id = enc.execute(
                f'SELECT rowid, * FROM "{table}" WHERE rowid > ? ORDER BY rowid LIMIT ?',
                (last_rowid, batch),
            ).fetchall()
        except Exception:
            enc.close()
            enc = open_enc(src_path)
            if batch == 1:
                last_rowid += 1
                bad_skips += 1
                if bad_skips % 50 == 0:
                    print(
                        f"      ... {ok_rows:,} 行  {bad_skips} 处损坏  {time.time() - t0:.0f}s",
                        flush=True,
                    )
                batch = min(BATCH_SIZE, 100)
            else:
                batch = max(1, batch // 4)
            continue

        if not rows_with_id:
            break

        last_rowid = rows_with_id[-1][0]
        rows = [r[1:] for r in rows_with_id]
        dst.executemany(f'INSERT OR IGNORE INTO "{table}" VALUES ({ph})', rows)
        dst.execute("COMMIT;")
        dst.execute("BEGIN;")
        ok_rows += len(rows)

        if batch < BATCH_SIZE:
            batch = min(BATCH_SIZE, batch * 2)

        if ok_rows % 500_000 == 0:
            elapsed = time.time() - t0
            rate = ok_rows / elapsed if elapsed else 0
            print(
                f"      ... {ok_rows:,}/{total_src:,} 行  ({rate:.0f} 行/s)", flush=True
            )

    # 如果重新打开了连接，关掉它（不关调用者传入的原始连接）
    if enc is not src:
        enc.close()

    elapsed = time.time() - t0
    rate = ok_rows / elapsed if elapsed else 0
    print(
        f"      ✓  {ok_rows:,}/{total_src:,} 行  跳过 {bad_skips} 处  ({rate:.0f} 行/s)  {elapsed:.0f}s"
    )
    return ok_rows, bad_skips


def main():
    src_hdr = pathlib.Path(INPUT_DB)
    clear = pathlib.Path(CLEAR_DB)
    out = pathlib.Path(OUTPUT_DB)
    work = pathlib.Path(WORK_DB)

    for p, name in [(src_hdr, INPUT_DB), (clear, CLEAR_DB)]:
        if not p.exists():
            sys.exit(f"[错误] 找不到文件: {p.resolve()}")

    if work.exists():
        work.unlink()

    print("=" * 60)

    # 1. 打开源库，列出所有表
    print(f"[1/4] 打开源库  {clear.name} ...", flush=True)
    src = open_enc(clear)
    tables = [
        r[0]
        for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    print(f"      共 {len(tables)} 张表")
    for t in tables:
        flag = "  ← 只建空表，不复制行" if t == SKIP_TABLE else ""
        print(f"        - {t}{flag}")

    # 2. 新建目标加密库
    print(f"\n[2/4] 新建目标库  {work.name} ...", flush=True)
    dst = sc.connect(str(work), isolation_level=None)
    dst.execute("PRAGMA cipher_page_size = 4096;")
    dst.execute(f"PRAGMA key = '{DB_KEY}';")
    dst.execute("PRAGMA kdf_iter = 4000;")
    dst.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    dst.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    dst.execute("PRAGMA journal_mode = WAL;")
    dst.execute("PRAGMA synchronous = NORMAL;")
    dst.execute("BEGIN;")

    # 3. 逐表处理
    print("\n[3/4] 复制表数据 ...", flush=True)
    total_ok = 0
    total_bad = 0
    t_all = time.time()

    # SQLite 内置表，不能手动建表（AUTOINCREMENT 等机制会自动维护）
    INTERNAL_TABLES = {
        "sqlite_sequence",
        "sqlite_stat1",
        "sqlite_stat2",
        "sqlite_stat3",
        "sqlite_stat4",
    }

    for i, table in enumerate(tables, 1):
        print(f"\n  [{i}/{len(tables)}] {table}", flush=True)
        if table in INTERNAL_TABLES:
            print("      ✓  内置表，跳过（SQLite 自动管理）")
            continue
        if table == SKIP_TABLE:
            # 只建空表
            ddl = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            ddl_safe = re.sub(
                r"^CREATE\s+TABLE\s+",
                "CREATE TABLE IF NOT EXISTS ",
                ddl,
                flags=re.IGNORECASE,
            )
            dst.execute(ddl_safe)
            dst.execute("COMMIT;")
            dst.execute("BEGIN;")
            print("      ✓  空表已建（跳过行复制）")
        else:
            ok, bad = copy_table(src, dst, table, clear)
            total_ok += ok
            total_bad += bad

    # 复制索引
    print("\n  [索引]", flush=True)
    indexes = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchall()
    dst.execute("COMMIT;")
    copied = 0
    for (ddl,) in indexes:
        try:
            dst.execute(ddl)
            copied += 1
        except Exception:
            pass
    print(f"      复制 {copied} 个索引")

    src.close()
    dst.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    dst.close()

    # 删掉 WAL/SHM 文件（如果有）
    for ext in ("-wal", "-shm"):
        pathlib.Path(WORK_DB + ext).unlink(missing_ok=True)

    print(
        f"\n      目标库  {work.stat().st_size:,} bytes  耗时 {time.time() - t_all:.0f}s"
    )

    # 4. 拼接头部
    print(f"\n[4/4] 读取头部 + 写出  {out.name} ...", flush=True)
    with open(src_hdr, "rb") as f:
        header = f.read(HEADER_SIZE)
    if len(header) != HEADER_SIZE:
        work.unlink(missing_ok=True)
        sys.exit(f"[错误] 头部读取不足：{len(header)} < {HEADER_SIZE}")

    t0 = time.time()
    with open(out, "wb") as dst_file:
        dst_file.write(header)
        with open(work, "rb") as wf:
            while chunk := wf.read(64 << 20):
                dst_file.write(chunk)

    work.unlink()
    size = out.stat().st_size
    print(f"      写出 {size:,} bytes  ({time.time() - t0:.0f}s)")

    print(f"\n{'=' * 60}")
    print(f"[完成] 数据行 {total_ok:,}  跳过损坏 {total_bad} 处")
    print(f"       输出: {out.resolve()}")
    print(
        f"       大小: {size / 1024**2:.0f} MB  (原始: {clear.stat().st_size / 1024**2:.0f} MB)"
    )


if __name__ == "__main__":
    main()
