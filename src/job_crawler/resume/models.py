from __future__ import annotations

from pydantic import BaseModel, Field


class Experience(BaseModel):
    company: str
    role: str | None = None
    period_raw: str | None = None
    start: str | None = None  # "YYYY.MM"
    end: str | None = None  # "YYYY.MM" or "현재"
    months: int | None = None
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    title: str
    period_raw: str | None = None
    bullets: list[str] = Field(default_factory=list)
    tech_tags: list[str] = Field(default_factory=list)


class ResumeProfile(BaseModel):
    name: str | None = None
    contact: str | None = None
    tech_stack: dict[str, list[str]] = Field(default_factory=dict)
    tech_stack_flat: list[str] = Field(default_factory=list)
    summary: str | None = None
    experiences: list[Experience] = Field(default_factory=list)
    total_experience_months: int = 0
    projects: list[Project] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    schools: list[str] = Field(default_factory=list)
    certs: list[str] = Field(default_factory=list)
    raw_text: str = ""

    @property
    def total_experience_years(self) -> float:
        return round(self.total_experience_months / 12, 1)
