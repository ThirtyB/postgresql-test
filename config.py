import os
from typing import Dict
from dotenv import load_dotenv


# Load environment variables from a local .env file if present
load_dotenv()


def get_db_config() -> Dict[str, str]:
    """Return database connection settings from environment variables.

    This function centralizes sensitive configuration so code elsewhere
    imports from here instead of reading os.environ directly.
    """
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": os.getenv("DB_PORT", "5432"),
        "database": os.getenv("DB_NAME", "exampledb"),
        "user": os.getenv("DB_USER", "user1"),
        "password": os.getenv("DB_PASSWORD", "123456"),
    }


def get_redis_config() -> Dict[str, str]:
    """Return Redis connection settings from environment variables."""
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", "6379")),
        "db": int(os.getenv("REDIS_DB", "0")),
        "password": os.getenv("REDIS_PASSWORD", None),
        "decode_responses": False,  # 设置为False以支持二进制数据
        "encoding": "utf-8",
    }


def get_jwt_config() -> Dict[str, str]:
    """Return JWT configuration settings."""
    return {
        "secret_key": os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this"),
        "algorithm": os.getenv("JWT_ALGORITHM", "HS256"),
        "access_token_expire_minutes": int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "360")),  # 6小时
        "refresh_token_expire_days": int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")),  # 7天
    }


