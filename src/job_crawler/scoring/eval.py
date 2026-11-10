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


def outcome_auc(scores: dict[int, int | None], passed: dict[int, bool]) -> float:
    """점수가 실제 서류 통과를 얼마나 잘 가르는지 (ROC AUC, 0.0~1.0, 0.5=무작위).

    Mann-Whitney 방식: 통과 공고 점수가 탈락 공고 점수보다 높은 쌍의 비율(동점 0.5).
    None 점수는 제외. 통과/탈락 중 한쪽이라도 비면 ValueError.
    """
    pos = [scores[i] for i, ok in passed.items() if ok and scores.get(i) is not None]
    neg = [scores[i] for i, ok in passed.items() if not ok and scores.get(i) is not None]
    if not pos or not neg:
        raise ValueError("통과/탈락 양쪽 표본이 모두 필요합니다")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))
