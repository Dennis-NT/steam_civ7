#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_run.py
按顺序自动运行 Steam 数据收集与处理流水线。
"""

import sys
import subprocess
from pathlib import Path

# 定义需要按顺序执行的脚本列表
SCRIPTS = [
    "steam_API.py",
    "count_words.py",
    "steam_sentiment_fill.py",
    "db_csv.py",
    "send_mail.py",
]


def run_script(script_path: Path) -> bool:
    """运行单个 Python 脚本，返回是否成功。"""
    print(f"\n{'='*60}")
    print(f"开始运行: {script_path.name}")
    print(f"{'='*60}")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=script_path.parent,
        capture_output=True,
        text=True,
    )

    # 始终打印子进程的 stdout/stderr，方便排查
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if result.returncode == 0:
        print(f"[成功] {script_path.name}")
        return True
    else:
        print(f"[失败] {script_path.name}，返回码: {result.returncode}")
        return False


def main() -> int:
    """主函数：按顺序执行所有脚本。"""
    base_dir = Path(__file__).parent.resolve()
    failed_scripts = []

    for script_name in SCRIPTS:
        script_path = base_dir / script_name
        if not script_path.exists():
            print(f"[错误] 脚本不存在: {script_path}")
            failed_scripts.append(script_name)
            continue

        if not run_script(script_path):
            failed_scripts.append(script_name)
            # 遇到失败立即中断
            break

    print(f"\n{'='*60}")
    print("执行完毕")
    print(f"{'='*60}")
    if failed_scripts:
        print(f"以下脚本执行失败: {failed_scripts}")
        return 1
    else:
        print("所有脚本执行成功！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
