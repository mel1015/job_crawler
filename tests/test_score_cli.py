"""jc-score CLI (claude_batch.score_main) stdin 파싱 테스트 — DB 미접근(save 모킹)."""
import io
import json

import pytest

from job_crawler.scoring import claude_batch


@pytest.fixture
def captured(monkeypatch):
    box = {}

    def fake_save(scores):
        box["scores"] = scores
        return len(scores)

    monkeypatch.setattr(claude_batch, "save_claude_scores", fake_save)
    return box


def _run(monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    claude_batch.score_main()


def test_plain_list(monkeypatch, captured, capsys):
    payload = [{"job_id": 1, "match_rate": 70, "verdict": "적합"}]
    _run(monkeypatch, json.dumps(payload))
    assert captured["scores"] == payload
    assert "저장 완료: 1/1건" in capsys.readouterr().out


def test_scores_wrapper(monkeypatch, captured):
    payload = {"scores": [{"job_id": 2}, {"job_id": 3}]}
    _run(monkeypatch, json.dumps(payload))
    assert captured["scores"] == payload["scores"]


def test_empty_input_exits(monkeypatch, captured):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "   ")


def test_invalid_json_exits(monkeypatch, captured):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "{not json")


def test_non_list_exits(monkeypatch, captured):
    with pytest.raises(SystemExit):
        _run(monkeypatch, json.dumps({"foo": "bar"}))
