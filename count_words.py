#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
count_words.py
读取数据库中的 comments 列，使用 jieba 分词并去除停用词后统计词频，
结果输出为 count_words.csv。
"""

import os
import csv
import sqlite3
import logging
from collections import Counter
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

import jieba

from SteamConfig import CFG


# ---------- 日志配置 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- 停用词加载 ----------
def load_stopwords(path: str) -> set[str]:
    """加载停用词文件，返回停用词集合。"""
    if not os.path.exists(path):
        logger.warning("停用词文件不存在: %s，将使用空停用词表", path)
        return set()

    stopwords = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            word = line.strip()
            if word:
                stopwords.add(word)
    logger.info("已加载 %d 个停用词", len(stopwords))
    return stopwords


# ---------- 分词与统计 ----------
def tokenize_text(text: str, stopwords: set[str]) -> list[str]:
    """对单条文本进行 jieba 分词，并过滤停用词、空白及单字。"""
    if not text:
        return []

    words = jieba.lcut(text)
    filtered = []
    for w in words:
        w = w.strip()
        # 过滤空串、单字、纯数字、停用词
        if len(w) < 2:
            continue
        if w.isdigit():
            continue
        if w in stopwords:
            continue
        filtered.append(w)
    return filtered


def fetch_comments(db_path: str, table_name: str, range_start: str, range_end: str) -> list[str]:
    """从指定表读取指定时间范围内的 comments 列内容。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        f'SELECT "comments" FROM "{table_name}" WHERE "publish_date" >= ? AND "publish_date" < ?',
        (range_start, range_end)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row[0] or "" for row in rows]


# ---------- 主流程 ----------
def main() -> None:
    db_path = CFG.DB_FILE
    stopwords_path = CFG.STOPWORDS_PATH

    now = datetime.now()
    today_15 = now.replace(hour=15, minute=0, second=0, microsecond=0)
    range_start = today_15 - timedelta(days=1)
    range_end = today_15

    range_start_str = range_start.strftime('%Y-%m-%d %H:%M:%S')
    range_end_str = range_end.strftime('%Y-%m-%d %H:%M:%S')
    file_tag = now.strftime('%Y%m%d')
    output_dir = os.path.join(CFG.BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"count_words_{file_tag}.csv")

    # 自动推导评论表名（取 TABLE_NAMES 中以 _comments 结尾的第一个）
    table_candidates = [t for t in CFG.TABLE_NAMES if t.endswith("_comments")]
    if not table_candidates:
        logger.error("配置中未找到以 _comments 结尾的表名，请检查 SteamConfig.py 的 TABLE_NAMES")
        return
    table_name = table_candidates[0]

    logger.info("数据库: %s", db_path)
    logger.info("目标表: %s", table_name)
    logger.info("时间范围: %s ~ %s", range_start_str, range_end_str)
    logger.info("停用词: %s", stopwords_path)
    logger.info("输出文件: %s", output_path)

    # 1. 加载停用词
    stopwords = load_stopwords(stopwords_path)

    # 2. 读取指定时间范围内的评论
    logger.info("正在读取 comments ...")
    comments = fetch_comments(db_path, table_name, range_start_str, range_end_str)
    logger.info("共读取 %d 条评论", len(comments))

    # 3. 分词与统计
    logger.info("开始分词与词频统计 ...")
    counter: Counter = Counter()
    for text in comments:
        words = tokenize_text(text, stopwords)
        counter.update(words)

    logger.info("去停用词后共统计到 %d 个不同词汇", len(counter))

    # 4. 输出 CSV（按词频降序）
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "count"])
        for word, count in counter.most_common():
            writer.writerow([word, count])

    logger.info("结果已保存至: %s", output_path)


if __name__ == "__main__":
    main()
