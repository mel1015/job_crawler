"""골든셋 회귀 평가 — 사람 정답 라벨 대비 점수 품질 측정.

스코어링 프롬프트(`contract.build_analysis_prompt`)를 변경하면 골든셋을 현재 프롬프트로
재평가해 `tests/golden/baseline_scores.json`을 갱신한다. `tests/test_scoring_regression.py`가
baseline의 MAE가 임계 이하인지 가드한다.
"""
from __future__ import annotations

from .contract import verdict_for_rate


def match_rate_mae(scores: dict[int, int | None], golden: dict[int, int]) -> float:
    """예측 점수와 사람 정답 라벨의 평균절대오차(MAE).

    None(평가불가) 점수는 비교에서 제외. 비교 가능한 쌍이 없으면 ValueError.
    """
    diffs = [
        abs(scores[i] - golden[i])
        for i in golden
        if i in scores and scores[i] is not None
    ]
    if not diffs:
        raise ValueError("비교 가능한 점수 쌍이 없습니다")
    return sum(diffs) / len(diffs)


def verdict_agreement(scores: dict[int, int | None], golden: dict[int, int]) -> float:
    """예측·정답을 verdict로 환산했을 때의 일치 비율 (0.0~1.0).

    verdict는 match_rate의 함수(`verdict_for_rate`)이므로 점수만으로 산출한다.
    """
    if not golden:
        return 0.0
    hit = sum(
        1
        for i in golden
        if i in scores
        and scores[i] is not None
        and verdict_for_rate(scores[i]) == verdict_for_rate(golden[i])
    )
    return hit / len(golden)
