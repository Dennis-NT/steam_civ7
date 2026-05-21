import os
import sqlite3
import logging
import datetime
from collections.abc import Iterable
import sys
from pathlib import Path

from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# 将项目根目录添加到 python path，以便导入 config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SteamConfig import CFG

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


target_date = datetime.datetime.now().strftime("%Y%m%d")
os.makedirs(CFG.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(CFG.LOG_DIR, f'db_init_{target_date}.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _tqdm_or_iter(iterable: Iterable, desc: str = "进度") -> Iterable:
    """返回带进度展示的可迭代对象；优先使用 tqdm，缺失时退化为简单文本进度条。

    参数:
        iterable: 需要迭代的对象（要求可计算长度以便显示进度）
        desc: 进度条前缀描述
    返回:
        可迭代对象，供 for 循环使用
    """
    if tqdm:
        return tqdm(iterable, desc=desc)
    
    seq = list(iterable)
    total = len(seq)

    def _generator():
        for idx, item in enumerate(seq, start=1):
            width = 30
            filled = int(width * idx / total) if total else width
            bar = "#" * filled + "." * (width - filled)
            print(f"\r{desc} [{bar}] {idx}/{total}", end="", flush=True)
            yield item
        print()  # 换行收尾

    return _generator()


def _resolve_columns(table_name: str) -> list[str]:
    """根据表名选择对应的字段配置。

    参数:
        table_name: 表名（以 _comments 或 _videos 结尾）
    返回:
        与该表类型匹配的字段列表
    """
    if table_name.endswith("_comments"):
        return CFG.COMMENTS_COLUMNS
    if table_name.endswith("_videos"):
        return CFG.VIDEOS_COLUMNS
    logger.warning("未知的表类型，使用评论表默认字段: %s", table_name)
    return CFG.COMMENTS_COLUMNS


def build_create_table_sql(table_name: str) -> str:
    """构建创建表的 SQL 文本，按表名选择字段并包含唯一列，同时强制注入分析状态字段。"""
    columns = _resolve_columns(table_name)
    cols_sql = ", ".join(columns)
    
    # 强制为评论表追加用于 DeepSeek 分析的"状态机"字段
    if table_name.endswith("_comments"):
        extra_cols = [
            "status TEXT DEFAULT 'pending'",  # 状态：pending(待处理), processing(处理中), done(已完成), error(错误)
        ]
        # 避免与 CFG 中可能已有的同名字段重复
        for col in extra_cols:
            col_name = col.split()[0]
            if not any(col_name in existing_col for existing_col in columns):
                cols_sql += f", {col}"
                
    return f'CREATE TABLE IF NOT EXISTS "{table_name}" ( {cols_sql} );'


def connect_database(db_path: str | None = None) -> sqlite3.Connection:
    """建立到 SQLite 数据库的连接；若路径为空则使用默认数据库名。

    参数:
        db_path: 数据库文件路径（缺省为当前目录下默认名称）
    返回:
        SQLite 连接对象
    """
    path = db_path or CFG.DB_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _sync_columns(conn: sqlite3.Connection, table_name: str) -> None:
    """检查表中缺失的列并自动添加（ALTER TABLE ADD COLUMN）。

    参数:
        conn: 已建立的 SQLite 连接
        table_name: 需要检查的表名
    """
    columns = _resolve_columns(table_name)
    cursor = conn.cursor()
    existing_cols = {row[1] for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()}

    # 从列定义中提取列名
    for col_def in columns:
        col_name = col_def.strip('"').split('"')[0] if '"' in col_def else col_def.split()[0]
        if col_name not in existing_cols:
            col_type = col_def.split('"')[-1].strip() if '"' in col_def else ' '.join(col_def.split()[1:])
            sql = f'ALTER TABLE "{table_name}" ADD COLUMN {col_name} {col_type}'
            cursor.execute(sql)
            logger.info("已为表 %s 添加缺失列: %s", table_name, col_name)

    # 同样处理 build_create_table_sql 中动态追加的 extra_cols
    if table_name.endswith("_comments"):
        extra_cols = ["status TEXT DEFAULT 'pending'"]
        for col in extra_cols:
            col_name = col.split()[0]
            if col_name not in existing_cols:
                sql = f'ALTER TABLE "{table_name}" ADD COLUMN {col}'
                cursor.execute(sql)
                logger.info("已为表 %s 添加缺失列: %s", table_name, col_name)

    conn.commit()
    cursor.close()


def create_tables(conn: sqlite3.Connection, table_names: Iterable[str]) -> None:
    """使用给定连接创建所有目标表，并在主体 for 循环中显示进度。

    参数:
        conn: 已建立的 SQLite 连接
        table_names: 需要创建的表名序列
    """
    cursor = conn.cursor()
    iterable = _tqdm_or_iter(list(table_names), desc="创建数据表")
    for name in iterable:
        sql = build_create_table_sql(name)
        cursor.execute(sql)
        logger.info("已创建/存在表: %s", name)
    conn.commit()
    cursor.close()

    # 同步缺失列
    for name in table_names:
        _sync_columns(conn, name)


def init_db(db_path: str | None = None) -> str:
    """初始化数据库文件并创建所有目标表。

    参数:
        db_path: 指定数据库文件路径；为空时使用默认路径
    返回:
        实际使用的数据库文件路径
    """
    logger.info("开始初始化数据库")
    conn = connect_database(db_path)
    try:
        create_tables(conn, CFG.TABLE_NAMES)
        real_path = conn.execute("PRAGMA database_list;").fetchone()[2]
        logger.info("数据库初始化完成: %s", real_path)
        return real_path
    finally:
        conn.close()


def main() -> None:
    """脚本入口：初始化默认数据库并创建配置中的表。"""
    try:
        init_db()
    except Exception as exc:
        logger.error("数据库初始化失败: %s", exc)
        raise


if __name__ == "__main__":
    main()

