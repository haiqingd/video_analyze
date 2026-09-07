"""全局配置：从 .env 与环境变量读取，运行时可被请求级参数覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class Settings:
    zhipu_api_key: str = field(default_factory=lambda: os.getenv("ZHIPU_API_KEY", "").strip())
    glm_model: str = field(default_factory=lambda: os.getenv("GLM_MODEL", "glm-5.3-flash").strip())
    # 最终攻略合成用更强的模型（分段笔记/事实抽取仍用 glm_model 省额度）
    glm_final_model: str = field(default_factory=lambda: os.getenv("GLM_FINAL_MODEL", "glm-5.3").strip())
    glm_base_url: str = field(
        default_factory=lambda: os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    )
    bilibili_sessdata: str = field(default_factory=lambda: os.getenv("BILIBILI_SESSDATA", "").strip())
    asr_model: str = field(default_factory=lambda: os.getenv("ASR_MODEL", "large-v3-turbo").strip())
    # LLM 同音字纠错（默认关闭：总结阶段会按参考文档自动纠正，独立纠错收益重复且有行对齐风险）
    asr_correct: bool = field(default_factory=lambda: os.getenv("ASR_CORRECT", "0") == "1")
    access_key: str = field(default_factory=lambda: os.getenv("ACCESS_KEY", "va2026").strip())
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8300")))


settings = Settings()
