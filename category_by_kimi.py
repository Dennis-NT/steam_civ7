# 请先安装 OpenAI SDK: pip install openai aiohttp
import os
import json
import logging
import sqlite3
import sys
import asyncio
import aiohttp
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent / '.env'
if not env_path.exists():
    env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

from typing import List, Tuple, Dict
from datetime import datetime, timedelta

try:
    from tqdm.auto import tqdm  # 更智能的环境选择（终端/Notebook）
except Exception:
    tqdm = None

# 初始化模块级日志记录器
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ---------------- 配置类（满足≥5个全局常量时统一管理） ----------------
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.SteamConfig import CFG

# 强制使用 Kimi 提供商
CFG.LLM_PROVIDER = "kimi"

class Config:
    """
    分类脚本配置类，统一管理数据库路径、日期范围、存储方式等。
    """
    PROJECT_ROOT: Path = Path(__file__).resolve().parent
    DB_FILE: Path = Path(CFG.DB_FILE)
    TABLE_NAME: str = CFG.TABLE_NAMES[0]
    DATE_SCOPE_DAYS: int = 7  # 最近N天
    LOG_LEVEL: int = logging.INFO
    # 日志文件配置
    LOG_DIR: Path = PROJECT_ROOT / 'logs'
    LOG_FILE_PREFIX: str = 'category_by_kimi'
    LOG_FILE_DATE_FMT: str = '%Y-%m-%d'
    # 异步批量处理配置
    ASYNC_BATCH_SIZE: int = 10  # 每批处理的评论数量
    MAX_CONCURRENT_REQUESTS: int = 10  # 最大并发请求数

# ---------------- LLM 提示词 ----------------
topics_str = ", ".join([f'"{t}"' for t in CFG.TOPICS_LIST])
prompt = f"""
    你是一位精准的游戏评论分析专家。你的任务是分析给定的用户评论，完成两件事：
    1. 识别出评论中涉及的所有预设话题。
    2. 判断该评论对每个已识别出的话题所表达的情感是【正面】、【中性】还是【负面】。

    # 规则：
    - 你必须从下面的“预设话题列表”中选择话题。如果评论内容不属于任何预设话题，请使用“其他”。
    - 情感必须是【正面】、【中性】或【负面】三者之一。
    - 你的输出必须是一个有效的JSON数组。数组中的每个对象都包含 "topic" 和 "sentiment" 两个键。
    - 如果一条评论没有明确的情感指向，或者只是在陈述事实，情感应为【中性】。
    - 不要输出任何解释、注释或者在JSON之外的任何文字。

    # 预设话题列表：
    [{topics_str}]

    # 示例：
    用户评论: "画面真的没得说，顶级水平，但是剧情太老套了，玩得我想睡觉。"
    你的输出:
    [
      {{"topic": "美术与音乐", "sentiment": "正面"}},
      {{"topic": "剧情与角色", "sentiment": "负面"}}
    ]

    现在，请分析用户评论并仅输出JSON数组：
    """

def setup_logging() -> None:
    """
    初始化日志文件输出，将日志写入 logs/category_by_kimi_YYYY-MM-DD.log，同时保留控制台输出。
    返回：
        None
    """
    try:
        # 确保日志目录存在
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        # 生成按日期命名的日志文件路径
        log_file_path = Config.LOG_DIR / f"{Config.LOG_FILE_PREFIX}_{datetime.now().strftime(Config.LOG_FILE_DATE_FMT)}.log"
        # 获取根日志器并设置格式
        root_logger = logging.getLogger()
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        # 防止重复添加文件句柄
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in root_logger.handlers)
        if not has_file_handler:
            fh = logging.FileHandler(str(log_file_path), encoding='utf-8')
            fh.setLevel(Config.LOG_LEVEL)
            fh.setFormatter(formatter)
            root_logger.addHandler(fh)
        logger.info("日志文件: %s", log_file_path)
    except Exception:
        logger.exception("初始化日志文件失败")

# ---------------- LLM 调用函数 ----------------

def build_batch_prompt(comments: List[Tuple[str, str]], base_prompt: str) -> str:
    """
    构建批量处理的prompt，将多条评论合并到一个请求中。
    参数：
        comments (List[Tuple[str, str]]): 评论列表，每个元素为(unique_id, comment_text)
        base_prompt (str): 基础提示词
    返回：
        str: 批量处理的prompt
    """
    batch_prompt = base_prompt + "\n\n请分析以下多条用户评论，为每条评论输出一个JSON数组。最终输出格式为：\n"
    batch_prompt += "{\n  \"results\": [\n    {\"comment_id\": \"评论ID1\", \"analysis\": [分析结果数组]},\n"
    batch_prompt += "    {\"comment_id\": \"评论ID2\", \"analysis\": [分析结果数组]}\n  ]\n}\n\n"
    
    for i, (unique_id, comment_text) in enumerate(comments, 1):
        batch_prompt += f"评论{i} (ID: {unique_id}): {comment_text}\n\n"
    
    batch_prompt += "请严格按照上述JSON格式输出，不要包含任何其他文字："
    return batch_prompt

def chunk_comments(comments: List[Tuple[str, str]], chunk_size: int = Config.ASYNC_BATCH_SIZE) -> List[List[Tuple[str, str]]]:
    """
    将评论列表分组，每组包含指定数量的评论。
    参数：
        comments (List[Tuple[str, str]]): 评论列表，每个元素为(unique_id, comment_text)
        chunk_size (int): 每组的评论数量，默认为配置中的ASYNC_BATCH_SIZE
    返回：
        List[List[Tuple[str, str]]]: 分组后的评论列表
    """
    chunks = []
    for i in range(0, len(comments), chunk_size):
        chunks.append(comments[i:i + chunk_size])
    return chunks

async def analyze_comments_batch_async(session: aiohttp.ClientSession, comments_batch: List[Tuple[str, str]], 
                                      base_prompt: str, api_key: str) -> List[Tuple[str, List[Dict[str, str]]]]:
    """
    异步批量分析评论。
    参数：
        session (aiohttp.ClientSession): HTTP会话
        comments_batch (List[Tuple[str, str]]): 评论批次，每个元素为(unique_id, comment_text)
        base_prompt (str): 基础提示词
        api_key (str): API密钥
    返回：
        List[Tuple[str, List[Dict[str, str]]]]: 分析结果列表，每个元素为(unique_id, analysis_result)
    """
    batch_prompt = build_batch_prompt(comments_batch, base_prompt)
    
    payload = {
        "model": CFG.ACTIVE_LLM_MODEL,
        "messages": [
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": batch_prompt}
        ],
        "stream": False
    }
    
    # 合并额外的 body 参数
    if CFG.ACTIVE_LLM_EXTRA_BODY:
        payload["extra_body"] = CFG.ACTIVE_LLM_EXTRA_BODY
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    max_retries = 1
    for attempt in range(max_retries + 1):
        try:
            async with session.post(CFG.ACTIVE_LLM_URL, 
                                   json=payload, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"API请求失败，状态码: {response.status} (第 {attempt + 1}/{max_retries + 1} 次尝试)")
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                    continue
                
                result = await response.json()
                content = result["choices"][0]["message"]["content"]
                
                try:
                    # 解析批量返回的JSON结果
                    batch_result = json.loads(content)
                    results = []
                    
                    if "results" in batch_result:
                        # 按照comment_id匹配结果
                        result_dict = {item["comment_id"]: item["analysis"] for item in batch_result["results"]}
                        for unique_id, _ in comments_batch:
                            if unique_id in result_dict:
                                results.append((unique_id, result_dict[unique_id]))
                            else:
                                results.append((unique_id, [{"topic": "其他", "sentiment": "中性"}]))
                    else:
                        # 如果格式不正确，为每条评论返回默认结果
                        results = [(uid, [{"topic": "其他", "sentiment": "中性"}]) for uid, _ in comments_batch]
                    
                    return results
                    
                except json.JSONDecodeError:
                    logger.warning(f"批量JSON解析失败 (第 {attempt + 1}/{max_retries + 1} 次尝试), 原始返回: {content}")
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                    continue
                    
        except Exception as e:
            logger.warning(f"批量API调用异常: {e} (第 {attempt + 1}/{max_retries + 1} 次尝试)")
            if attempt < max_retries:
                await asyncio.sleep(1)
            continue

    logger.error("所有重试均失败，本批次将保持 NULL")
    return []

# ---------------- 数据库读取/写入 ----------------

def fetch_recent_comments(db_path: str, days: int = 7, only_missing_ts: bool = False) -> List[Tuple[str, str]]:
    """
    读取最近N天内的评论文本与唯一ID。
    参数：
        db_path (str): SQLite数据库文件路径。
        days (int): 最近天数范围，默认7。
        only_missing_ts (bool): 若为 True，则仅返回 "topic/sentiment" 为空的评论，用于列存储避免重复处理。
    返回：
        List[Tuple[unique_id, comment_content]]: 唯一ID与评论文本列表。
    """
    sql = (
        f"SELECT unique_id, comments FROM {Config.TABLE_NAME} "
        "WHERE date(publish_date) >= date('now', '-%d day') "
        "AND comments IS NOT NULL AND TRIM(comments) <> ''"
    ) % days
    if only_missing_ts:
        sql += ' AND ("topic/sentiment" IS NULL OR TRIM("topic/sentiment") = \'\')'
    rows: List[Tuple[str, str]] = []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        logger.info("读取最近%d天评论数: %d", days, len(rows))
    except Exception as e:
        logger.exception("读取评论失败: %s", e)
    finally:
        if conn:
            conn.close()
    return rows

def ensure_topic_sentiment_column(db_path: str) -> None:
    """
    确保 comments 表存在名为 "topic/sentiment" 的列（TEXT）。
    参数：
        db_path (str): 数据库路径。
    返回：
        None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({Config.TABLE_NAME})")
        cols = [row[1] for row in cur.fetchall()]
        if "topic/sentiment" not in cols:
            cur.execute(f'ALTER TABLE {Config.TABLE_NAME} ADD COLUMN "topic/sentiment" TEXT')
            conn.commit()
            logger.info(f'已添加列 "topic/sentiment" 到 {Config.TABLE_NAME} 表')
        else:
            logger.info('已检测到列 "topic/sentiment"，无需添加')
    except Exception:
        logger.exception('检查/添加 "topic/sentiment" 列失败')
    finally:
        if conn:
            conn.close()


def update_comment_topic_sentiment_column(db_path: str, updates: List[Tuple[str, List[Dict[str, str]]]]) -> int:
    """
    将分类结果写入 comments."topic/sentiment" 列。
    仅在该列为空时执行更新，已有数据的记录将跳过，不重复处理。
    参数：
        db_path (str): 数据库路径。
        updates (List[Tuple[unique_id, analysis]]): 待更新列表。
        返回：
        int: 成功更新的记录数。
    """
    conn = None
    success = 0
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        for unique_id, analysis in updates:
            ts_value = json.dumps(analysis, ensure_ascii=False)
            cur.execute(
                f'''UPDATE {Config.TABLE_NAME} SET "topic/sentiment" = ?
                WHERE unique_id = ? AND ("topic/sentiment" IS NULL OR TRIM("topic/sentiment") = '')''',
                (ts_value, unique_id)
            )
            success += cur.rowcount
        conn.commit()
        logger.info('已更新 "topic/sentiment" 列记录数: %d', success)
    except Exception:
        logger.exception('更新 "topic/sentiment" 列失败')
    finally:
        if conn:
            conn.close()
    return success

async def process_comments_async(comments: List[Tuple[str, str]], base_prompt: str, 
                               db_path: str) -> None:
    """
    异步并发处理评论分析，使用信号量控制并发数。
    参数：
        comments (List[Tuple[str, str]]): 评论列表
        base_prompt (str): 基础提示词
        db_path (str): 数据库路径
    返回：
        None
    """
    api_key = os.environ.get(CFG.ACTIVE_LLM_API_KEY_NAME)
    if not api_key:
        logger.error(f"未检测到环境变量 {CFG.ACTIVE_LLM_API_KEY_NAME}，请先配置后再运行。")
        return
    
    # 将评论分组
    comment_chunks = chunk_comments(comments, Config.ASYNC_BATCH_SIZE)
    logger.info("评论总数: %d，分为 %d 组，每组 %d 条", len(comments), len(comment_chunks), Config.ASYNC_BATCH_SIZE)
    
    # 创建信号量控制并发数
    semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_REQUESTS)
    
    async def process_chunk_with_semaphore(session: aiohttp.ClientSession, chunk: List[Tuple[str, str]]) -> List[Tuple[str, List[Dict[str, str]]]]:
        """带信号量控制的批次处理函数"""
        async with semaphore:
            return await analyze_comments_batch_async(session, chunk, base_prompt, api_key)
    
    # 创建HTTP会话
    timeout = aiohttp.ClientTimeout(total=60)  # 60秒超时
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 创建所有任务
        tasks = [process_chunk_with_semaphore(session, chunk) for chunk in comment_chunks]
        
        # 使用asyncio.as_completed逐个处理完成的任务，实现每收到一组结果就写入数据库
        completed_batches = 0
        total_saved = 0
        
        # tqdm进度条（如果可用）
        pbar = None
        if tqdm:
            pbar = tqdm(total=len(comment_chunks), desc="异步批量分析进度", unit="批")

        for coro in asyncio.as_completed(tasks):
            try:
                batch_results = await coro
                completed_batches += 1
                
                # 立即写入数据库
                if batch_results:
                    try:
                        updated = update_comment_topic_sentiment_column(db_path, batch_results)
                        total_saved += updated
                        logger.info("批次 %d/%d 完成，更新列记录数: %d，累计: %d", 
                                  completed_batches, len(comment_chunks), updated, total_saved)
                    except Exception as e:
                        logger.exception("批次结果写入数据库失败: %s", e)
                
                if pbar:
                    pbar.update(1)
                        
            except Exception as e:
                logger.exception("批次处理异常: %s", e)
                completed_batches += 1
                if pbar:
                    pbar.update(1)
        
        if pbar:
            pbar.close()

        logger.info("异步批量处理完成，总写库数: %d", total_saved)

# ---------------- 主流程 ----------------

def run_analysis(db_path: str, days: int = Config.DATE_SCOPE_DAYS) -> None:
    """
    运行最近N天的评论主题/情感分类，并写回数据库。
    参数：
        db_path (str): 数据库路径。
        days (int): 最近天数范围。
    返回：
        None
    说明：
        使用异步批量处理模式
    """
    # 确保列存在，并只抓取列为空的记录
    ensure_topic_sentiment_column(str(db_path))
    comments = fetch_recent_comments(str(db_path), days, only_missing_ts=True)

    if not comments:
        logger.info("无待分析评论，流程结束。")
        return

    logger.info("使用异步批量处理模式")
    asyncio.run(process_comments_async(comments, prompt, str(db_path)))

if __name__ == '__main__':
    # 初始化日志等级
    logging.getLogger().setLevel(Config.LOG_LEVEL)
    # 初始化日志到文件
    setup_logging()
    # 运行分析流程
    run_analysis(Config.DB_FILE, Config.DATE_SCOPE_DAYS)
