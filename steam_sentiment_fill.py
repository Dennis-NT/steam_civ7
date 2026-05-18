"""根据Steam的voted_up字段填充评论情感结果。

此脚本连接到SQLite数据库，读取配置中指定表（如 `NBA2K26_comments`）中
`platform` 为 `steam` 的记录，从 `metadata` JSON 中解析 `voted_up` 字段，并将其映射为
`sentiment` 文本：`True` → `正面`，`False` → `负面`。

支持通过命令行参数指定数据库路径和表名。
"""

import argparse
import json
import logging
import sqlite3
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

from tqdm import tqdm

import sys

# 将项目根目录添加到 python path，以便导入 config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SteamConfig import CFG


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def connect_db(db_path: Path) -> sqlite3.Connection:
    """建立到SQLite数据库的连接并启用Row字典访问。

    参数:
        db_path: 数据库文件路径。

    返回:
        sqlite3.Connection 对象。
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_sentiment_column(conn: sqlite3.Connection, table_name: str) -> None:
    """确保目标表存在 `sentiment` 文本列，不存在时自动新增。

    参数:
        conn: 数据库连接。
        table_name: 表名。
    """
    cur = conn.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cur.fetchall()]
    if "sentiment" not in columns:
        logging.info("表 %s 缺少 sentiment 列，正在新增", table_name)
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN sentiment TEXT")
        conn.commit()


def parse_voted_up(metadata_str: Optional[str]) -> Optional[str]:
    """从metadata JSON解析voted_up并映射为中文情感文本。

    参数:
        metadata_str: JSON字符串，期望包含键 `voted_up`。

    返回:
        映射后的情感文本：`正面` 或 `负面`；若无法解析则返回 None。
    """
    if not metadata_str:
        return None
    try:
        data = json.loads(metadata_str)
    except Exception:
        return None

    val = data.get("voted_up", None)
    if isinstance(val, bool):
        return "正面" if val else "负面"
    if isinstance(val, (int, float)):
        return "正面" if bool(val) else "负面"
    if isinstance(val, str):
        v = val.strip().lower()
        if v in {"true", "1", "yes", "y", "t"}:
            return "正面"
        if v in {"false", "0", "no", "n", "f"}:
            return "负面"
    return None


def fetch_steam_rows(conn: sqlite3.Connection, table_name: str) -> List[sqlite3.Row]:
    """获取指定表中platform为steam的记录（返回rowid与metadata）。

    参数:
        conn: 数据库连接。
        table_name: 表名。

    返回:
        包含 `rowid` 与 `metadata` 的行列表。
    """
    sql = f"SELECT rowid, metadata FROM {table_name} WHERE platform = ?"
    cur = conn.execute(sql, ("steam",))
    rows = cur.fetchall()
    return rows


def build_updates(rows: Sequence[sqlite3.Row], table_name: str) -> List[Tuple[str, int]]:
    """为待更新记录构建批量更新参数列表。

    参数:
        rows: 原始行序列，需包含 `rowid` 与 `metadata`。
        table_name: 当前处理的表名，仅用于进度输出。

    返回:
        形如 `(sentiment_text, rowid)` 的更新参数列表。
    """
    updates: List[Tuple[str, int]] = []
    for row in tqdm(rows, desc=f"解析 {table_name} 元数据", unit="条"):
        sentiment = parse_voted_up(row["metadata"]) if row["metadata"] is not None else None
        if sentiment is not None:
            updates.append((sentiment, int(row["rowid"])))
            # tqdm.write(f"{table_name} rowid={row['rowid']} → {sentiment}")
    return updates


def apply_updates(conn: sqlite3.Connection, table_name: str, updates: Iterable[Tuple[str, int]]) -> int:
    """执行批量更新，将sentiment写入目标表。

    参数:
        conn: 数据库连接。
        table_name: 表名。
        updates: 更新参数序列 `(sentiment_text, rowid)`。

    返回:
        实际更新的记录数。
    """
    updates_list = list(updates)
    if not updates_list:
        return 0
    sql = f"UPDATE {table_name} SET sentiment = ? WHERE rowid = ?"
    conn.executemany(sql, updates_list)
    conn.commit()
    return len(updates_list)


def process_table(conn: sqlite3.Connection, table_name: str) -> int:
    """处理单张评论表：确保列存在、提取steam记录、解析并批量写入情感。

    参数:
        conn: 数据库连接。
        table_name: 表名。

    返回:
        更新的记录数量。
    """
    logging.info("开始处理表: %s", table_name)
    ensure_sentiment_column(conn, table_name)
    rows = fetch_steam_rows(conn, table_name)
    logging.info("表 %s 读取到 %d 条 steam 记录", table_name, len(rows))
    updates = build_updates(rows, table_name)
    updated = apply_updates(conn, table_name, updates)
    logging.info("表 %s 已更新 %d 条记录", table_name, updated)
    return updated


def main(argv: Optional[Sequence[str]] = None) -> None:
    """命令行入口：读取数据库并处理目标评论表。

    支持参数：
    - `--db`: 数据库文件路径，默认使用 init_db 配置
    - `--tables`: 需处理的表名列表，默认使用 init_db 配置

    参数:
        argv: 可选的参数列表，用于测试或嵌入调用。
    """
    # 从 CFG 获取默认配置
    default_db_path = Path(CFG.DB_FILE)
    default_tables = CFG.TABLE_NAMES

    parser = argparse.ArgumentParser(description="根据Steam voted_up填充sentiment")
    parser.add_argument(
        "--db",
        type=Path,
        default=default_db_path,
        help=f"SQLite数据库文件路径 (默认: {default_db_path})",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        default=default_tables,
        help=f"需要处理的表名列表 (默认: {default_tables})",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db
    tables: List[str] = list(args.tables)

    if not db_path.exists():
        logging.error("数据库文件不存在: %s", db_path)
        # 尝试提示用户是否运行过 steam_API.py
        logging.info("提示: 请先运行 steam_API.py 进行数据抓取")
        return

    conn = connect_db(db_path)
    try:
        total_updated = 0
        for table in tqdm(tables, desc="处理数据表", unit="表"):
            updated = process_table(conn, table)
            total_updated += updated
            tqdm.write(f"{table} 更新数量: {updated}")
        logging.info("总计更新 %d 条记录", total_updated)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
