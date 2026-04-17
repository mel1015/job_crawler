"""Gemini 호출 래퍼. JSON 스키마를 강제해 구조화 응답만 받는다."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "match_rate": {
            "type": "integer",
            "description": "0~100 정수. 예상 합격률(서류/1차 면접 통과 가능성 종합).",
        },
        "verdict": {
            "type": "string",
            "enum": ["강한매치", "적합", "애매", "부적합"],
        },
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "이력서 대비 공고 요건을 충족하는 항목 3~6개. 구체적으로.",
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "부족하거나 불명확한 요건 2~5개. 우대사항 미충족 포함.",
        },
        "red_flags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "지원 시 명확한 결격/위험 요소. 없으면 빈 배열.",
        },
        "action_tip": {
            "type": "string",
            "description": "지원 전 이력서/자소서에서 강조하거나 보강할 한 문장.",
        },
    },
    "required": ["match_rate", "verdict", "strengths", "gaps", "red_flags", "action_tip"],
}


@dataclass
class GeminiResult:
    data: dict[str, Any]
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model or settings.gemini_model
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY 가 설정되지 않았습니다.")

        import google.generativeai as genai  # lazy import

        genai.configure(api_key=self.api_key)
        self._genai = genai
        self._model = genai.GenerativeModel(self.model_name)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(GeminiError),
        reraise=True,
    )
    def generate_json(self, prompt: str, system: str | None = None) -> GeminiResult:
        try:
            response = self._model.generate_content(
                [system, prompt] if system else prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": RESPONSE_SCHEMA,
                    "temperature": 0.2,
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"gemini call failed: {e}")
            raise GeminiError(str(e)) from e

        text = (response.text or "").strip()
        if not text:
            raise GeminiError("empty response from gemini")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise GeminiError(f"invalid json: {text[:300]}") from e

        usage = getattr(response, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", None) if usage else None
        tokens_out = getattr(usage, "candidates_token_count", None) if usage else None

        return GeminiResult(
            data=data,
            model=self.model_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
