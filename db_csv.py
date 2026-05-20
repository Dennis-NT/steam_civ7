import csv
import sqlite3
import os
import sys
from datetime import datetime

# 将项目根目录添加到 python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from SteamConfig import CFG


def export_today_comments() -> str:
    """将数据库中日期为今天的所有评论导出为 CSV 文件。

    返回:
        生成的 CSV 文件路径。
    """
    today = datetime.now().strftime("%Y%m%d")
    today_date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.join(CFG.BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_filename = f"comments_{today}.csv"
    output_path = os.path.join(output_dir, output_filename)

    table_name = f"{CFG.KEYWORD}_comments"

    conn = sqlite3.connect(CFG.DB_FILE)
    cursor = conn.cursor()

    # 获取表头
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    headers = [row[1] for row in cursor.fetchall()]

    # 查询今天日期的数据
    cursor.execute(
        f'SELECT * FROM "{table_name}" WHERE "publish_date" = ?',
        (today_date_str,)
    )
    rows = cursor.fetchall()

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    conn.close()

    print(f"已导出 {len(rows)} 条记录到: {output_path}")
    return output_path


if __name__ == "__main__":
    export_today_comments()
