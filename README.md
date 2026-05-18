# Steam Civilization VII 舆情监测

本项目用于抓取并分析 Steam 平台《文明 VII》（AppID: 3472040）的玩家评论，实现舆情监测与情感分析。

## 功能模块

| 文件 | 说明 |
|---|---|
| `SteamConfig.py` | 全局配置中心（AppID、数据库名、路径、关键词等） |
| `steam_API.py` | Steam 评论抓取：通过 Steam API 分页获取评论并写入 SQLite |
| `init_db.py` | 数据库初始化：创建评论表、情感表等基础表结构 |
| `count_words.py` | 词频统计：对评论内容进行 jieba 分词与停用词过滤，输出 `count_words.csv` |
| `category_by_kimi.py` | 使用 Kimi API 对评论进行主题分类与情感打标 |
| `category_by_deepseek.py` | 使用 DeepSeek API 对评论进行主题分类与情感打标 |
| `steam_sentiment_fill.py` | 情感分析结果回填与汇总统计 |

## 快速开始

1. 安装依赖
   ```bash
   pip install requests python-dotenv jieba tqdm
   ```

2. 配置环境变量
   在项目根目录创建 `.env` 文件：
   ```env
   KIMI_API_KEY=your_kimi_api_key
   ```

3. 初始化数据库
   ```bash
   python init_db.py
   ```

4. 抓取评论
   ```bash
   python steam_API.py
   ```

5. 词频统计
   ```bash
   python count_words.py
   ```

6. AI 分类 / 情感分析（任选其一）
   ```bash
   python category_by_kimi.py
   # 或
   python category_by_deepseek.py
   ```

## 项目结构

```
steam_civ7/
├── SteamConfig.py           # 配置
├── steam_API.py             # 数据抓取
├── init_db.py               # 数据库初始化
├── count_words.py           # 词频统计
├── category_by_kimi.py      # Kimi 分类
├── category_by_deepseek.py  # DeepSeek 分类
├── steam_sentiment_fill.py  # 情感回填
├── resource/
│   └── baidu_stopwords.txt  # 停用词表
└── .env                     # 环境变量（勿提交）
```

## 注意事项

- `.env` 文件包含 API 密钥等敏感信息，**请勿提交到 Git**。
- `logs/`、`raw data/`、`reference/` 及本地 `.db` 数据库为运行时生成文件，已加入 `.gitignore`。
- 抓取评论时请注意 Steam API 的速率限制，脚本内已内置随机休眠与重试机制。
