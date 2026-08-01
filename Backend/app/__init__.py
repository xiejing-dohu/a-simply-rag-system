"""智能 RAG 后端应用根包

自动加载 Backend/.env 环境变量配置文件。
"""

from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")
