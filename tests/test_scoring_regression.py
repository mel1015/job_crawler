"""골든셋 회귀 테스트 — 스코어링 점수 품질이 임계 이하로 유지되는지 가드.

LLM은 비결정적이라 테스트에서 직접 호출하지 않는다. 대신:
- `golden/golden_set.json`: 사람 정답 라벨이 붙은 골든셋 20건 (입력 본문 포함)
- `golden/baseline_scores.json`: 현재 프롬프트로 평가한 점수 (회귀 기준선)

프롬프트(`contract.build_analysis_prompt`)를 바꾸면 골든셋을 재평가해 baseline_scores.json을
갱신하고, 이 테스트가 사람 라벨 대비 MAE가 임계를 넘지 않는지 확인한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_crawler.scoring.eval import match_rate_mae, verdict_agreement

GOLDEN_DIR = Path(__file__).parent / "golden"

# 골든셋 30건 기준. 룰 적용 전 20건 MAE 14.0 → 룰3 적용 후 20건 8.9 →
# 어려운 2차 10건 추가로 30건 baseline 10.5. 노이즈 바닥(~2.8)을 감안해
# 회귀 가드 임계는 12.0 (룰 적용 전 수준으로 퇴행하면 실패, 현재는 여유).
MAE_THRESHOLD = 12.0
VERDICT_AGREEMENT_MIN = 0.60


@pytest.fixture(scope="module")
def golden() -> dict[int, int]:
    data = json.loads((GOLDEN_DIR / "golden_set.json").read_text(encoding="utf-8"))
    return {item["job_id"]: item["human_label"] for item in data}


@pytest.fixture(scope="module")
def baseline() -> dict[int, int | None]:
    data = json.loads((GOLDEN_DIR / "baseline_scores.json").read_text(encoding="utf-8"))
    return {int(k): v for k, v in data.items()}


def test_golden_set_integrity():
    data = json.loads((GOLDEN_DIR / "golden_set.json").read_text(encoding="utf-8"))
    assert len(data) == 30
    for item in data:
        assert set(item) >= {"job_id", "title", "body_text", "human_label"}
        assert 0 <= item["human_label"] <= 100
        assert item["body_text"].strip(), f"본문 비어있음: {item['job_id']}"


def test_baseline_covers_golden(golden, baseline):
    assert set(baseline) == set(golden), "baseline과 golden의 job_id 집합 불일치"


def test_baseline_mae_within_threshold(golden, baseline):
    mae = match_rate_mae(baseline, golden)
    assert mae <= MAE_THRESHOLD, f"MAE {mae:.1f} > 임계 {MAE_THRESHOLD} — 스코어링 품질 퇴행"


def test_baseline_verdict_agreement(golden, baseline):
    agree = verdict_agreement(baseline, golden)
    assert agree >= VERDICT_AGREEMENT_MIN, f"verdict 일치 {agree:.0%} < {VERDICT_AGREEMENT_MIN:.0%}"


# ── eval 함수 단위 테스트 ──────────────────────────────────────────────────────

def test_match_rate_mae_basic():
    assert match_rate_mae({1: 50, 2: 70}, {1: 40, 2: 80}) == 10.0


def test_match_rate_mae_skips_none():
    # job 2는 None(평가불가)이라 제외 → job 1만으로 MAE 5
    assert match_rate_mae({1: 45, 2: None}, {1: 40, 2: 90}) == 5.0


def test_match_rate_mae_raises_when_no_pairs():
    with pytest.raises(ValueError):
        match_rate_mae({1: None}, {1: 50})


def test_verdict_agreement():
    # 50→애매 vs 라벨 55→애매(일치), 90→강한매치 vs 라벨 30→부적합(불일치)
    assert verdict_agreement({1: 50, 2: 90}, {1: 55, 2: 30}) == 0.5
