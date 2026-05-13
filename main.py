"""
NTQQ NT 聊天数据库解密工具

流程：
  1. 剥离 1024 字节自定义头  →  nt_msg_clear.db
  2. sqlcipher3 验证解密参数（正确 PRAGMA 顺序）
  3. 逐表 rowid 游标分页导出 + 损坏自动跳过  →  nt_msg_plain.db

PRAGMA 正确顺序（实测验证，顺序错误会导致解密失败）：
    PRAGMA cipher_page_size = 4096;   ← 必须在 key 之前
    PRAGMA key = '...';
    PRAGMA kdf_iter = 4000;
    PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
    PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;

依赖：uv add sqlcipher3
"""
import os
import re
import sys
import time
import sqlite3
import pathlib

from dotenv import load_dotenv
import sqlcipher3.dbapi2 as sc

load_dotenv()


# ─── 配置（修改这里）────────────────────────────────────────────────────────
INPUT_DB  = "nt_msg.db"          # 原始输入（含 1024 字节 NTQQ 自定义头）
CLEAR_DB  = "nt_msg_clear.db"    # 剥头后的 SQLCipher 文件（中间产物）
OUTPUT_DB = "nt_msg_plain.db"    # 最终明文 SQLite 输出

DB_KEY = os.getenv("NTQQ_DB_KEY") or ""  # 优先读取环境变量；也可直接在引号内填写回退密钥
# ────────────────────────────────────────────────────────────────────────────

HEADER_SIZE = 1024      # NTQQ 自定义头长度（固定值）
BATCH_SIZE  = 5000      # 每批读取行数（遇到损坏时自动缩小）


# ── 步骤 1：剥离头部 ─────────────────────────────────────────────────────────

def strip_header(src: pathlib.Path, dst: pathlib.Path) -> None:
    expected = src.stat().st_size - HEADER_SIZE
    if dst.exists() and dst.stat().st_size == expected:
        print(f"[跳过] {dst.name} 已存在 ({dst.stat().st_size:,} bytes)")
        return
    print(f"[1/3] 剥离头部  {src.name} → {dst.name} ...", flush=True)
    with open(src, "rb") as f:
        f.seek(HEADER_SIZE)
        with open(dst, "wb") as out:
            while chunk := f.read(64 << 20):   # 64 MB 分块，避免大文件占满内存
                out.write(chunk)
    actual = dst.stat().st_size
    if actual != expected:
        raise RuntimeError(f"写出大小不符：期望 {expected:,}，实际 {actual:,}")
    print(f"      写出 {actual:,} bytes ✓")


# ── 步骤 2：打开加密数据库 ────────────────────────────────────────────────────

def open_enc(path: pathlib.Path):
    """打开 SQLCipher 加密数据库，返回已验证的连接"""
    conn = sc.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA cipher_page_size = 4096;")   # 必须在 key 之前
    conn.execute(f"PRAGMA key = '{DB_KEY}';")
    conn.execute("PRAGMA kdf_iter = 4000;")
    conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    conn.execute("SELECT count(*) FROM sqlite_master;").fetchone()  # 触发实际解密验证
    return conn


# ── 步骤 3：逐表导出 ─────────────────────────────────────────────────────────

def export_table(enc_path: pathlib.Path, plain: sqlite3.Connection, table: str) -> tuple[int, int]:
    """
    将加密库中的一张表导出到明文库。

    策略：rowid 游标分页（WHERE rowid > last ORDER BY rowid LIMIT N）
      - 不受随机主键值域的影响，始终 O(log N) 定位
      - 遇到损坏页：重连 + 批次缩小至 1；单行也坏则 rowid+1 跳过
      - 支持断点续跑：从 plain 库的 max(rowid) 继续

    返回：(成功插入行数, 跳过损坏次数)
    """
    enc = open_enc(enc_path)

    # 建表（IF NOT EXISTS 支持续跑）
    ddl = enc.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    ddl_safe = re.sub(r"^CREATE\s+TABLE\s+", "CREATE TABLE IF NOT EXISTS ", ddl, flags=re.IGNORECASE)
    plain.execute(ddl_safe)
    plain.commit()

    ncols = len(enc.execute(f'PRAGMA table_info("{table}")').fetchall())
    ph = ",".join("?" * ncols)

    # 断点：从输出库的 max(rowid) 续跑
    try:
        last_rowid = plain.execute(f'SELECT max(rowid) FROM "{table}"').fetchone()[0] or 0
    except Exception:
        last_rowid = 0

    total_src = enc.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    ok_rows = 0
    bad_skips = 0
    batch = BATCH_SIZE
    t0 = time.time()

    while True:
        try:
            # rowid 作游标；SELECT rowid, * 让 rowid 作为额外首列
            rows_with_id = enc.execute(
                f'SELECT rowid, * FROM "{table}" WHERE rowid > ? ORDER BY rowid LIMIT ?',
                (last_rowid, batch)
            ).fetchall()
        except Exception:
            # 损坏：重连 + 缩小批次
            enc.close()
            enc = open_enc(enc_path)
            if batch == 1:
                last_rowid += 1     # 跳过这个坏 rowid
                bad_skips += 1
                if bad_skips % 50 == 0:
                    print(f"      ... {ok_rows:,} 行  {bad_skips} 处损坏  {time.time()-t0:.0f}s", flush=True)
                batch = min(BATCH_SIZE, 100)
            else:
                batch = max(1, batch // 4)
            continue

        if not rows_with_id:
            break

        last_rowid = rows_with_id[-1][0]
        rows = [r[1:] for r in rows_with_id]    # 去掉首列 rowid，还原原始列顺序
        plain.executemany(f'INSERT OR IGNORE INTO "{table}" VALUES ({ph})', rows)
        plain.commit()
        ok_rows += len(rows)

        if batch < BATCH_SIZE:
            batch = min(BATCH_SIZE, batch * 2)  # 恢复批次大小

        if ok_rows % 500_000 == 0:
            elapsed = time.time() - t0
            rate = ok_rows / elapsed if elapsed else 0
            print(f"      ... {ok_rows:,}/{total_src:,} 行  ({rate:.0f} 行/s)", flush=True)

    enc.close()
    elapsed = time.time() - t0
    rate = ok_rows / elapsed if elapsed else 0
    print(f"      ✓  {ok_rows:,}/{total_src:,} 行  "
          f"跳过 {bad_skips} 处  ({rate:.0f} 行/s)  {elapsed:.0f}s")
    return ok_rows, bad_skips


def copy_indexes(enc_path: pathlib.Path, plain: sqlite3.Connection) -> int:
    """将加密库的索引定义复制到明文库"""
    enc = open_enc(enc_path)
    indexes = enc.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchall()
    enc.close()
    copied = 0
    for (ddl,) in indexes:
        try:
            plain.execute(ddl)
            copied += 1
        except Exception:
            pass    # 已存在或依赖表不存在时跳过
    plain.commit()
    return copied


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    src   = pathlib.Path(INPUT_DB)
    clear = pathlib.Path(CLEAR_DB)
    out   = pathlib.Path(OUTPUT_DB)

    if not src.exists():
        sys.exit(f"[错误] 找不到输入文件: {src.resolve()}")

    print("=" * 60)

    # 1. 剥头
    strip_header(src, clear)

    # 2. 验证解密参数
    print(f"\n[2/3] 验证解密参数 (密钥长度 {len(DB_KEY)} 字节) ...", flush=True)
    try:
        enc = open_enc(clear)
    except Exception as e:
        sys.exit(f"[错误] 解密失败，请检查密钥: {e}")
    tables = [r[0] for r in enc.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    enc.close()
    print(f"      密钥正确 ✓  共 {len(tables)} 张表")
    for t in tables:
        print(f"        - {t}")

    # 3. 逐表导出
    print(f"\n[3/3] 导出明文数据库 → {out} ...", flush=True)
    plain = sqlite3.connect(str(out))
    plain.execute("PRAGMA journal_mode = WAL;")
    plain.execute("PRAGMA synchronous = NORMAL;")
    plain.execute("PRAGMA cache_size = -65536;")    # 64 MB 页缓存

    total_ok  = 0
    total_bad = 0
    t_all = time.time()

    INTERNAL = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat2",
                 "sqlite_stat3", "sqlite_stat4"}

    for i, table in enumerate(tables, 1):
        print(f"\n  [{i}/{len(tables)}] {table}", flush=True)
        if table in INTERNAL:
            print(f"      ✓  内置表，跳过")
            continue
        ok, bad = export_table(clear, plain, table)
        total_ok  += ok
        total_bad += bad

    # 复制索引
    print(f"\n  [索引]", flush=True)
    n_idx = copy_indexes(clear, plain)
    print(f"      复制 {n_idx} 个索引")

    plain.close()

    size    = out.stat().st_size
    elapsed = time.time() - t_all
    print(f"\n{'=' * 60}")
    print(f"[完成] 总计 {total_ok:,} 行  跳过 {total_bad} 处损坏")
    print(f"       输出: {out.resolve()}")
    print(f"       大小: {size / 1024**3:.2f} GB  耗时: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
