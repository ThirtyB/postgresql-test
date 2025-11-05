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


