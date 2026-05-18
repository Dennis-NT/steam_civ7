import hashlib
import sqlite3
import os
import json
import logging
import time
import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

import requests
from urllib.parse import quote_plus
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import init_db  # 引入数据库初始化模块
from SteamConfig import CFG

# 初始化日志与目录
os.makedirs(CFG.LOG_DIR, exist_ok=True)
os.makedirs(CFG.OUTPUT_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(CFG.LOG_DIR, f"steam_reviews_{datetime.datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def _iter_with_progress(iterable: List[Any], desc: str = "进度", unit: str = "条"):
    """
    返回带进度展示的可迭代对象；优先使用 tqdm，缺失时退化为简单文本进度。

    参数：
        iterable: 需要迭代的对象（会转换为列表以便显示总数）
        desc: 进度条前缀描述
        unit: 进度单位文本（如 条/页）
    返回：
        可迭代对象，供 for 循环使用
    """
    try:
        from tqdm import tqdm  # type: ignore
        return tqdm(list(iterable), desc=desc, unit=unit)  # type: ignore
    except Exception:
        seq = list(iterable)
        total = len(seq)

        def _generator():
            width = 30
            for idx, item in enumerate(seq, start=1):
                filled = int(width * idx / total) if total else width
                bar = "#" * filled + "." * (width - filled)
                print(f"\r{desc} [{bar}] {idx}/{total} {unit}", end="", flush=True)
                yield item
            print()

        return _generator()


def _build_url(app_id: int, cursor: str) -> str:
    """
    按模板拼接评论接口 URL。

    参数：
        app_id: Steam AppID。
        cursor: 游标字符串；会进行 URL 编码。
    返回：
        完整请求 URL。
    """
    return CFG.API_URL_TEMPLATE.format(
        AppID=str(app_id),
        Cursor=quote_plus(cursor),
        Filter=CFG.FILTER,
        Language=CFG.LANGUAGE,
        ReviewType=CFG.REVIEW_TYPE,
        PurchaseType=CFG.PURCHASE_TYPE,
        NumPerPage=str(CFG.NUM_PER_PAGE),
    )


def _create_session() -> requests.Session:
    """
    创建并返回一个 requests 会话对象。

    返回：
        已配置的 `requests.Session`。
    """
    s = requests.Session()
    if CFG.PROXIES:
        s.proxies.update(CFG.PROXIES)
    s.trust_env = True
    return s


def _to_date_str(ts: int) -> Optional[str]:
    """
    将 Unix 时间戳（秒）转换为 `YYYY-MM-DD` 字符串。

    参数：
        ts: Unix 时间戳（秒）。
    返回：
        日期字符串。若失败返回 None。
    """
    try:
        if ts == 0:
            return None
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def _transform_review(app_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Steam 原始评论字典转换为统一字段结构。
    
    规则：
        - unique_id: md5(comments + publish_date)
        - metadata: json(voted_up, language)
        - 缺失字段: 赋值为 None (对应数据库 NULL)

    参数：
        app_id: 当前应用的 AppID。
        item: 原始评论对象（来自 API）。
    返回：
        统一字段字典，包含平台/用户/内容/点赞数/日期/唯一ID等。
    """
    author = item.get("author") or {}
    ts_created = int(item.get("timestamp_created") or 0)
    
    # 提取并处理字段，缺失赋值为 None
    comments = item.get("review")
    if not comments: # Empty string or None
        comments = None
        
    user_id = author.get("steamid")
    if not user_id:
        user_id = None
        
    publish_date = _to_date_str(ts_created)
    
    # 生成 unique_id
    # 使用 comments + publish_date 的哈希值
    # 哈希计算时使用空字符串代替 None
    hash_input = (comments or "") + (publish_date or "")
    unique_id = hashlib.md5(hash_input.encode("utf-8")).hexdigest()
    
    # 构建 metadata
    metadata_dict = {
        "voted_up": bool(item.get("voted_up") or False),
        "language": str(item.get("language") or CFG.LANGUAGE),
    }
    
    # votes_up
    like = item.get("votes_up")
    # if like is None, it remains None
    
    return {
        "platform": "steam",
        "oid": int(app_id),
        "user": user_id,
        "comments": comments,
        "like": like,
        "publish_date": publish_date,
        "unique_id": unique_id,
        "metadata": json.dumps(metadata_dict, ensure_ascii=False),
    }


class DatabaseManager:
    """
    数据库管理器，支持批量写入。
    """
    def __init__(self, db_path: str, table_name: str, batch_size: int = 25):
        self.db_path = db_path
        self.table_name = table_name
        self.batch_size = batch_size
        self.buffer: List[Dict[str, Any]] = []
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.cursor = self.conn.cursor()
        # 确保表存在（可选，或者依赖外部 init_db）
        # 这里我们假设表已经由 init_db.py 创建，或者我们可以在这里尝试创建
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.flush()
        if self.conn:
            self.conn.close()

    def add_item(self, item: Dict[str, Any]):
        self.buffer.append(item)
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        
        if not self.cursor or not self.conn:
            return

        sql = f'''
            INSERT INTO "{self.table_name}" 
            ("platform", "user", "comments", "like", "publish_date", "oid", "unique_id", "metadata")
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT("unique_id") DO UPDATE SET
            "like"=MAX(IFNULL("like",0), excluded."like"),
            "publish_date"=CASE WHEN ("publish_date" IS NULL OR "publish_date"="") THEN excluded."publish_date" ELSE "publish_date" END,
            "user"=CASE WHEN ("user" IS NULL OR "user"="") THEN excluded."user" ELSE "user" END,
            "comments"=CASE WHEN ("comments" IS NULL OR "comments"="") THEN excluded."comments" ELSE "comments" END,
            "oid"=CASE WHEN ("oid" IS NULL) THEN excluded."oid" ELSE "oid" END,
            "platform"=CASE WHEN ("platform" IS NULL OR "platform"="") THEN excluded."platform" ELSE "platform" END,
            "metadata"=CASE WHEN ("metadata" IS NULL OR "metadata"="") THEN excluded."metadata" ELSE "metadata" END
        '''
        
        data_to_insert = []
        for item in self.buffer:
            data_to_insert.append((
                item["platform"],
                item["user"],
                item["comments"],
                item["like"],
                item["publish_date"],
                item["oid"],
                item["unique_id"],
                item["metadata"]
            ))
        
        try:
            self.cursor.executemany(sql, data_to_insert)
            self.conn.commit()
            logger.info(f"批量存入数据库: {self.cursor.rowcount} 条")
        except Exception as e:
            logger.error(f"数据库写入失败: {e}")
        
        self.buffer.clear()


def fetch_reviews(
    app_id: Optional[int] = None,
    stop_date_str: Optional[str] = None,
    max_pages: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """
    基于 cursor 翻页抓取 Steam 评论列表。

    参数：
        app_id: 目标 AppID，默认使用配置中的 `CFG.APP_ID`。
        stop_date_str: 停止日期（YYYY-MM-DD）。当页内出现更早评论时，保留不早于该日期的评论并停止抓取。
        max_pages: 限制最大翻页数（用于测试或限流）。
        session: 外部传入的 `requests.Session`，便于测试或复用连接。
    返回：
        评论字典列表。
    """
    app_id = int(app_id or CFG.APP_ID)
    stop_date_str = stop_date_str if stop_date_str else CFG.STOP_DATE_STR
    stop_epoch: Optional[int] = None
    if stop_date_str:
        try:
            dt = datetime.datetime.strptime(stop_date_str, "%Y-%m-%d")
            stop_epoch = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        except Exception:
            logger.warning("停止日期格式不正确，忽略：%s", stop_date_str)

    sess = session or _create_session()
    cursor = "*"
    prev_cursor = ""
    page_count = 0
    all_items: List[Dict[str, Any]] = []

    # 数据库配置
    # 优先使用 init_db 中的数据库名，保持一致
    # db_name = init_db.CFG.DB_NAME
    # db_path = os.path.join(CFG.BASE_DIR, db_name)
    db_path = CFG.DB_FILE
    table_name = f"{CFG.KEYWORD}_comments"

    # 确保数据库和表已初始化
    # 使用 init_db 模块为当前关键词创建对应的表
    try:
        conn = init_db.connect_database(db_path)
        try:
            init_db.create_tables(conn, [table_name])
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")

    # 进度：页循环（未知总数，逐页更新）
    try:
        from tqdm import tqdm  # type: ignore
        page_bar = tqdm(desc="抓取页", unit="页")  # type: ignore
    except Exception:
        page_bar = None

    # 使用 DatabaseManager 上下文管理器
    with DatabaseManager(db_path, table_name, batch_size=25) as db_manager:
        while True:
            if max_pages is not None and page_count >= int(max_pages):
                logger.info("达到最大页数限制：%d，停止翻页", int(max_pages))
                break
    
            url = _build_url(app_id, cursor)
            last_error: Optional[Exception] = None
            terminated_by_stop_date: bool = False
            for attempt in range(1, CFG.MAX_RETRIES + 1):
                try:
                    resp = sess.get(url, timeout=CFG.REQUEST_TIMEOUT)
                    data = resp.json()
                    if not data or int(data.get("success", 0)) != 1:
                        raise RuntimeError(f"请求成功标记异常：{data!r}")
                    reviews = data.get("reviews") or []
                    # all_raw_items.extend(reviews)  # 收集原始评论
                    next_cursor = str(data.get("cursor") or "")
    
                    # 页内转换与时间过滤（大量循环，添加进度条）
                    transformed: List[Dict[str, Any]] = []
                    iterable = _iter_with_progress(list(reviews), desc=f"处理第{page_count+1}页", unit="条")
                    for it in iterable:
                        obj = _transform_review(app_id, it)
                        if stop_epoch is not None:
                            # Fix: Check raw item 'it' for timestamp, not transformed 'obj'
                            if int(it.get("timestamp_created", 0)) < stop_epoch:
                                continue
                        transformed.append(obj)
                        # 逐条加入 DB 管理器
                        db_manager.add_item(obj)
    
                    all_items.extend(transformed)
                    page_count += 1
                    if page_bar is not None:
                        page_bar.update(1)  # type: ignore
    
                    logger.info(
                        "第 %d 页：原始 %d 条，保留 %d 条，总计 %d 条",
                        page_count,
                        len(reviews),
                        len(transformed),
                        len(all_items),
                    )
    
                    # 终止条件：cursor 不变化 或 页为空；若存在停止日期且页被截断，也终止
                    if next_cursor == prev_cursor or len(reviews) == 0:
                        logger.info("检测到无更多评论：cursor 不变或页为空，结束")
                        break
                    if stop_epoch is not None and len(transformed) < len(reviews):
                        logger.info("根据停止日期截断本页，结束翻页")
                        terminated_by_stop_date = True
                        break
    
                    prev_cursor = cursor
                    cursor = next_cursor
                    time.sleep(2)
                    break  # 当前页成功
                except Exception as e:
                    last_error = e
                    logger.warning("请求或解析异常（尝试 %d/%d）：%s", attempt, CFG.MAX_RETRIES, str(e))
                    time.sleep(max(CFG.SLEEP_BOUNDS[0], min(CFG.SLEEP_BOUNDS[1], 0.3 * attempt)))
            else:
                logger.error("达到最大重试次数，跳过当前页：%s", url)
    
            # 检查是否结束（根据上一次成功的状态）
            if last_error is None:
                # 正常已处理本页，继续下一轮由条件决定
                if terminated_by_stop_date or next_cursor == prev_cursor or len(reviews) == 0:
                    break
                continue
            else:
                # 连续失败情况下，尝试判定是否应停止
                if max_pages is not None and page_count >= int(max_pages):
                    break
                # 失败后尝试继续下页，但 cursor 未更新则停止
                if cursor == prev_cursor:
                    break

    if page_bar is not None:
        try:
            page_bar.close()  # type: ignore
        except Exception:
            pass

    logger.info("累计抓取 %d 条评论（%d 页）", len(all_items), page_count)
    return all_items


def write_ndjson(items: List[Dict[str, Any]], out_path: str) -> None:
    """
    将评论列表写入 NDJSON 文件，每行一个 JSON 对象。

    参数：
        items: 评论字典列表。
        out_path: 输出文件的绝对路径（.ndjson）。
    返回：
        无；写入完成记录日志。
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        from tqdm import tqdm  # type: ignore
        iterable = tqdm(list(items), desc="写入NDJSON", unit="条")  # type: ignore
    except Exception:
        iterable = list(items)

    with open(out_path, "w", encoding="utf-8") as f:
        for obj in iterable:  # type: ignore
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    logger.info("已写入 NDJSON 文件: %s", out_path)


def main() -> None:
    """
    入口函数：抓取配置指定 AppID 的评论，保存为 NDJSON 并存入数据库。

    行为：
        - 使用 `CFG` 配置抓取评论。
        - 可通过 `CFG.STOP_DATE_STR` 控制停止日期。
        - 将结果写入 `raw data/steam` 目录，文件名包含日期。
        - 将结果批量存入 SQLite 数据库（每 25 条）。
    """
    items = fetch_reviews(app_id=CFG.APP_ID, stop_date_str=CFG.STOP_DATE_STR)
    
    # 1. 保存 NDJSON
    out_name = f"{CFG.APP_ID}_steam_reviews_{datetime.datetime.now().strftime('%Y%m%d')}.ndjson"
    out_path = os.path.join(CFG.OUTPUT_DIR, out_name)
    write_ndjson(items, out_path)


if __name__ == "__main__":
    main()
