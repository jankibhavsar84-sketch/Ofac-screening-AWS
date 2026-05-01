from __future__ import annotations

from .config import settings
from .repository import JobRepository


def main() -> None:
    repository = JobRepository(settings.app_db_path, settings.app_db_url)
    target = "APP_DB_URL" if repository.is_postgres else settings.app_db_path
    print(f"Database schema validated for {target}")


if __name__ == "__main__":
    main()
