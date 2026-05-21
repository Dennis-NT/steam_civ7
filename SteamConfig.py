import os
from typing import Optional, Tuple
from datetime import datetime, timedelta

class SteamConfig:
    """
    集中管理 Steam 评论抓取的全局配置。

    字段说明：
        APP_ID: 目标应用的 AppID（默认 3472040）。
        API_URL_TEMPLATE: 评论接口 URL 模板。
        FILTER: 评论筛选方式（recent/all）。
        LANGUAGE: 语言筛选（schinese/all 等）。
        REVIEW_TYPE: 评论类型（all/positive/negative）。
        PURCHASE_TYPE: 购买类型筛选（all/steam/steam_community）。
        NUM_PER_PAGE: 每页评论数量上限（最大 100）。
        REQUEST_TIMEOUT: 单次请求超时秒数。
        MAX_RETRIES: 单页请求最大重试次数。
        SLEEP_BOUNDS: 两次请求之间的随机休眠范围。
        BASE_DIR/LOG_DIR/OUTPUT_DIR: 路径配置。
        STOP_DATE_STR: 爬取的停止日期（YYYY-MM-DD），早于该日期的评论不再抓取。
        KEY_WORDS: 统一关键词列表（用于分析与提取模块）。
        PLATFORM_LIST: 统一平台列表（用于统计与输出模块）。
    """

    def __init__(self) -> None:
        self.KEYWORD: str = "CIV7_2026"
        self.DB_NAME: str = f"{self.KEYWORD}.db"
        self.SITE_TITLE: str = f"《{self.KEYWORD}》舆情监测系统"
        self.LOGO_IMAGE: str = f"pictures/{self.KEYWORD}.png"
        self.LOGO_ALT: str = self.KEYWORD
        self.APP_ID: int = 1295660
        self.STOP_DATE_STR: Optional[str] = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')  # 动态设置为昨天
        
        # App/Web Configuration
        self.DATA_SOURCE_TYPE: str = "json"  # json, api, generated
        self.API_ENDPOINT: Optional[str] = None
        self.API_TIMEOUT: int = 10
        self.CACHE_BUSTING: bool = True

        
        # 统一关键词列表（用于分析与提取模块）
        self.KEY_WORDS: Tuple[str, ...] = (
            '游戏','垃圾','投篮','一代','25','2K','模式','好玩','闪退','一个'
        )
        # 统一平台列表（用于统计与输出模块）
        # 格式：(platform_key, platform_label)
        self.PLATFORM_LIST: list[Tuple[str, str]] = [
            ('steam', 'Steam'),
            ('xiaoheihe', '小黑盒'),
            ('tieba', '贴吧'),
            ('douyin', '抖音'),
            ('bilibili', 'Bilibili')
        ]

        # LLM Provider Configuration
        # Options: "mimo", "deepseek", "kimi"
        self.LLM_PROVIDER: str = "deepseek"

        # Xiaomi MiMo API 配置
        self.MIMO_API_URL: str = "https://api.xiaomimimo.com/v1/chat/completions"
        self.MIMO_MODEL: str = "mimo-v2-flash"

        # DeepSeek API 配置
        self.DEEPSEEK_API_URL: str = "https://api.deepseek.com/chat/completions"
        self.DEEPSEEK_MODEL: str = "deepseek-chat"

        # Kimi (Moonshot AI) API 配置
        self.KIMI_API_URL: str = "https://api.moonshot.cn/v1/chat/completions"
        self.KIMI_MODEL: str = "moonshot-v1-8k"

        # 预设话题列表 (用于分类)
        self.TOPICS_LIST: list[str] = [
            "游戏性", "剧情与角色", "美术与音乐", "技术问题/Bug", "网络与服务器", "付费与商业化", 
            "新手体验", "UI/UX", "其他", "建议", "游戏系统", "运营活动", "技术体验", "社区治理", "政治文化法律"
        ]

        self.API_URL_TEMPLATE: str = (
            "https://store.steampowered.com/appreviews/{AppID}?json=1&cursor={Cursor}&filter={Filter}&language={Language}&review_type={ReviewType}&purchase_type={PurchaseType}&num_per_page={NumPerPage}"
        )
        self.FILTER: str = "recent"
        self.LANGUAGE: str = "schinese"
        self.REVIEW_TYPE: str = "all"
        self.PURCHASE_TYPE: str = "all"
        self.NUM_PER_PAGE: int = 100
        self.REQUEST_TIMEOUT: int = 15
        self.MAX_RETRIES: int = 3
        self.SLEEP_BOUNDS: tuple[float, float] = (2.4, 4.2)
        
        # 如果你后续想关闭代理，在 SteamConfig.py 里把那段代理配置改成：
        # self.PROXIES: Optional[dict] = None 即可。
        # 代理配置：默认使用本地 6478 端口（如 Clash/V2Ray 等），可从环境变量覆盖
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:6478"
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "http://127.0.0.1:6478"
        self.PROXIES: Optional[dict] = {
            "http": http_proxy,
            "https": https_proxy,
        }
        # self.PROXIES: Optional[dict] = None
        
        # 动态获取项目根目录（本文件位于项目根目录下）
        self.BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
        
        self.LOG_DIR: str = os.path.join(self.BASE_DIR, "logs")
        self.OUTPUT_DIR: str = os.path.join(self.BASE_DIR, "raw data", "steam")    
        self.DB_FILE: str = os.path.join(self.BASE_DIR, "database", self.DB_NAME)
        self.STATIC_DIR: str = os.path.join(self.BASE_DIR, "static")
        self.DIST_DIR: str = os.path.join(self.BASE_DIR, "dist")
        self.STOPWORDS_PATH: str = os.path.join(self.BASE_DIR, "resource", "baidu_stopwords.txt")
        self.DATA_JSON_INDEX_PATH: str = os.path.join(self.BASE_DIR, "raw data", "index_data.json")
        self.DATA_JSON_DAILY_PATH: str = self.DATA_JSON_INDEX_PATH
        self.DATA_JSON_WEEKLY_PATH: str = os.path.join(self.BASE_DIR, "raw data", "weekly_data.json")
        self.DATA_JSON_MONTHLY_PATH: str = os.path.join(self.BASE_DIR, "raw data", "monthly_data.json")
        
        # 数据库配置
        self.TABLE_NAMES: list[str] = [
            f"{self.KEYWORD}_comments",
        ]
        # comments 与 videos 两类表的字段配置
        self.COMMENTS_COLUMNS: list[str] = [
            '"platform" TEXT',
            '"user" TEXT',
            '"comments" TEXT',
            '"like" INTEGER',
            '"publish_date" TEXT',
            '"oid" INTEGER',
            '"unique_id" TEXT UNIQUE',
            '"metadata" TEXT',
            '"url" TEXT',
        ]
        self.VIDEOS_COLUMNS: list[str] = [
            '"platform" TEXT',
            '"user" TEXT',
            '"title" TEXT',
            '"description" TEXT',
            '"like" INTEGER',
            '"play" INTEGER',
            '"reply" INTEGER',
            '"favorite" INTEGER',
            '"coin" INTEGER',
            '"share" INTEGER',
            '"publish_date" TEXT',
            '"oid" INTEGER',
            '"bvid" TEXT',
            '"unique_id" TEXT UNIQUE',
            '"metadata" TEXT',
        ]

    @property
    def ACTIVE_LLM_URL(self) -> str:
        if self.LLM_PROVIDER == "mimo":
            return self.MIMO_API_URL
        if self.LLM_PROVIDER == "kimi":
            return self.KIMI_API_URL
        return self.DEEPSEEK_API_URL

    @property
    def ACTIVE_LLM_MODEL(self) -> str:
        if self.LLM_PROVIDER == "mimo":
            return self.MIMO_MODEL
        if self.LLM_PROVIDER == "kimi":
            return self.KIMI_MODEL
        return self.DEEPSEEK_MODEL

    @property
    def ACTIVE_LLM_API_KEY_NAME(self) -> str:
        if self.LLM_PROVIDER == "mimo":
            return "MIMO_API_KEY"
        if self.LLM_PROVIDER == "kimi":
            return "KIMI_API_KEY"
        return "DEEPSEEK_API_KEY"

    @property
    def ACTIVE_LLM_EXTRA_BODY(self) -> dict:
        if self.LLM_PROVIDER == "mimo":
            return {"thinking": {"type": "disabled"}}
        if self.LLM_PROVIDER == "kimi" and "k2" in self.ACTIVE_LLM_MODEL.lower():
            return {"thinking": {"type": "disabled"}}
        return {}

CFG = SteamConfig()
