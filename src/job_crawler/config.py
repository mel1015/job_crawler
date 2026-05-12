from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    resume_path: Path = Path("resume.md")

    desired_roles: str = ""
    desired_regions: str = ""
    desired_salary_min: int = 0
    desired_experience_min: int = 0
    desired_experience_max: int = 99

    # 필터링 세분화
    desired_positions: str = ""   # 직군 화이트리스트 (빈값=전체 허용)
    blacklist_companies: str = "" # 기업명 블랙리스트
    required_keywords: str = ""   # 제목 필수 키워드 (빈값=DEV_KEYWORDS 사용)

    database_url: str = "sqlite:///./data/jobs.db"

    web_host: str = "127.0.0.1"
    web_port: int = 8000

    crawl_concurrency: int = 2
    request_delay_sec: float = 2.0
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    )

    log_level: str = "INFO"

    @property
    def roles_list(self) -> list[str]:
        return [s.strip() for s in self.desired_roles.split(",") if s.strip()]

    @property
    def regions_list(self) -> list[str]:
        return [s.strip() for s in self.desired_regions.split(",") if s.strip()]

    @property
    def positions_list(self) -> list[str]:
        return [s.strip() for s in self.desired_positions.split(",") if s.strip()]

    @property
    def blacklist_companies_list(self) -> list[str]:
        return [s.strip() for s in self.blacklist_companies.split(",") if s.strip()]

    @property
    def required_keywords_list(self) -> list[str]:
        return [s.strip() for s in self.required_keywords.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
