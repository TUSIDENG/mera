"""LLM 离线打分管线单测：mock chat 模型，不触网。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.models import Base, ModelSnapshot
from app.llm_scoring.graph import ScoreResult, score_snapshot
from app.llm_scoring.prompt import DIMENSIONS, build_prompt
from app.repositories import Repository


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def repo(db_session: Session) -> Repository:
    repo = Repository(db_session)
    db_session.add(
        ModelSnapshot(
            model_id="gpt-4o",
            provider="openai",
            benchmark_score=Decimal("80.0"),
            scores={"intelligence": 80.0, "coding": None},
            score_source="intelligence",
            data={"sources": {"aa": {"raw_model_id": "GPT-4o", "record": {"score": 80}}}},
        )
    )
    db_session.commit()
    return repo


class FakeStructuredLLM:
    """模拟 llm.with_structured_output(...).invoke(prompt)。"""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.prompts: list[str] = []

    def with_structured_output(self, schema: Any, **_: Any) -> FakeStructuredLLM:
        return self

    def invoke(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return self._result


def _settings(**overrides: Any) -> Settings:
    return Settings(llm_scorer_enabled=True, **overrides)


def _snapshot(db_session: Session) -> ModelSnapshot:
    return db_session.scalar(
        select(ModelSnapshot).where(ModelSnapshot.model_id == "gpt-4o")
    )


class TestScoreSnapshot:
    def test_writes_llm_scores_and_rationale(self, repo: Repository, db_session: Session):
        llm = FakeStructuredLLM(
            ScoreResult(
                overall=86.25,
                dims={"intelligence": 86.0, "coding": 90.0, "image": None},
                rationale="AA 综合分 80，代码榜表现强",
                confidence=0.8,
            )
        )
        assert score_snapshot(repo, _settings(), model_id="gpt-4o", llm=llm)
        snap = _snapshot(db_session)
        assert snap.score_source == "llm:deepseek/deepseek-chat"
        assert snap.benchmark_score == Decimal("86.25")
        # 未输出维度补 null；非法维度被剔除，仅保留 DIMENSIONS
        assert snap.scores == {
            "intelligence": 86.0,
            "coding": 90.0,
            "agentic": None,
            "long_context": None,
            "image": None,
            "video": None,
        }
        assert snap.data["llm_score"]["rationale"] == "AA 综合分 80，代码榜表现强"
        assert snap.data["llm_score"]["scorer"] == "deepseek/deepseek-chat"
        # 采集原始数据仍在
        assert snap.data["sources"]["aa"]["record"]["score"] == 80

    def test_out_of_range_scores_clamped(self, repo: Repository, db_session: Session):
        llm = FakeStructuredLLM(
            ScoreResult(overall=150.0, dims={"coding": 120.0}, rationale="越界")
        )
        assert score_snapshot(repo, _settings(), model_id="gpt-4o", llm=llm)
        snap = _snapshot(db_session)
        assert snap.benchmark_score == Decimal(100)
        assert snap.scores["coding"] == 100.0

    def test_all_null_result_not_persisted(self, repo: Repository, db_session: Session):
        """LLM 判完全无法打分：不落库，保留采集回落分。"""
        llm = FakeStructuredLLM(ScoreResult(overall=None, dims={}, rationale="无数据"))
        assert not score_snapshot(repo, _settings(), model_id="gpt-4o", llm=llm)
        snap = _snapshot(db_session)
        assert snap.score_source == "intelligence"
        assert snap.benchmark_score == Decimal("80.0")

    def test_missing_snapshot_returns_false(self, repo: Repository):
        llm = FakeStructuredLLM(ScoreResult(overall=1.0, dims={}))
        assert not score_snapshot(repo, _settings(), model_id="ghost", llm=llm)
        assert llm.prompts == []  # load 失败即终止，不调用 LLM

    def test_llm_error_propagates_for_retry(self, repo: Repository):
        """LLM 调用异常向上抛（任务层重试兜底），不写库。"""
        llm = FakeStructuredLLM(error=TimeoutError("boom"))
        with pytest.raises(TimeoutError):
            score_snapshot(repo, _settings(), model_id="gpt-4o", llm=llm)

    def test_unknown_provider_returns_false(self, repo: Repository):
        settings = _settings(llm_scorer_provider="unknown")
        assert not score_snapshot(repo, settings, model_id="gpt-4o")

    def test_no_api_key_skips(self, repo: Repository):
        """未注入 llm 且无 key：视为关闭，不构建真实模型。"""
        settings = _settings(deepseek_api_key=None)
        assert not score_snapshot(repo, settings, model_id="gpt-4o")

    def test_switch_provider_and_model(self, repo: Repository, db_session: Session):
        """支持切换打分模型：score_source 记录实际使用的 provider/model。"""
        llm = FakeStructuredLLM(ScoreResult(overall=70.0, dims={"coding": 70.0}))
        settings = _settings(llm_scorer_provider="chatgpt", llm_scorer_model="gpt-4o")
        assert score_snapshot(repo, settings, model_id="gpt-4o", llm=llm)
        snap = _snapshot(db_session)
        assert snap.score_source == "llm:chatgpt/gpt-4o"


class TestBuildPrompt:
    def test_contains_model_and_sources(self):
        prompt = build_prompt(
            "gpt-4o", "openai",
            {"aa": {"raw_model_id": "GPT-4o", "record": {"score": 80}}},
            {"intelligence": 80.0},
            max_chars=8000,
        )
        assert "gpt-4o" in prompt
        assert "openai" in prompt
        assert "intelligence" in prompt
        assert "raw_model_id" in prompt

    def test_truncates_long_payload(self):
        sources = {"aa": {"record": {"blob": "x" * 10000}}}
        prompt = build_prompt("m", "p", sources, {}, max_chars=100)
        assert "...(truncated)" in prompt
        assert len(prompt) < 10000

    def test_dimensions_cover_image_and_video(self):
        assert set(DIMENSIONS) == {
            "intelligence", "coding", "agentic", "long_context", "image", "video"
        }
