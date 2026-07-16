import json
from dataclasses import dataclass
from pathlib import Path

from ai_research_agent.analysis.relevance import decision_for_score, evaluate_article_relevance
from ai_research_agent.ingestion.models import CollectedArticle


@dataclass
class MockLLMClient:
    response: str
    model_name: str = "mock-llm"

    def generate_markdown(self, prompt: str) -> str:
        assert "research_keywords" in prompt
        assert "research_profile.yaml" in prompt
        assert "待评估文章" in prompt
        assert "economics" in prompt
        assert "AI-based computational social science methods" in prompt
        assert "LLM-based social simulation" in prompt
        return self.response


def test_css_paper_ranks_high(tmp_path: Path) -> None:
    article = CollectedArticle(
        title="Computational social science study of AI governance",
        source="Anthropic",
        url="https://example.com/css-governance",
        published_date="2026-07-13",
        summary=(
            "A research paper using digital trace data, agent-based modeling, and NLP to study "
            "frontier model governance and institutional accountability."
        ),
        category="AI研究机构",
    )

    result = evaluate_article_relevance(
        article=article,
        client=MockLLMClient(response=_response(score=9, categories=["计算社会科学", "AI治理"])),
        profile_path=_profile(tmp_path),
        research_profile_path=_research_profile(tmp_path),
    )

    assert result.score == 9
    assert result.categories == ["计算社会科学", "AI治理"]
    assert result.research_value_score.css_relevance == 9
    assert result.decision == "full_research_analysis"
    assert "治理" in result.why_relevant_to_user


def test_ai_hardware_news_ranks_low(tmp_path: Path) -> None:
    article = CollectedArticle(
        title="New AI accelerator improves benchmark throughput",
        source="Google DeepMind",
        url="https://example.com/ai-chip",
        published_date="2026-07-13",
        summary="A hardware optimization update focused on GPU utilization and benchmark speed.",
        category="AI研究机构",
    )

    result = evaluate_article_relevance(
        article=article,
        client=MockLLMClient(
            response=_response(
                score=2,
                categories=["硬件与基础设施"],
                research_value_score={
                    "novelty": 3,
                    "methodological_contribution": 2,
                    "relevance_to_css": 1,
                    "future_research_proposal_potential": 1,
                },
                why_relevant_to_user="这主要是硬件和 benchmark 优化，对用户的CSS研究议程关联很弱。",
            )
        ),
        profile_path=_profile(tmp_path),
        research_profile_path=_research_profile(tmp_path),
    )

    assert result.score == 2
    assert result.research_value_score.css_relevance == 1
    assert result.decision == "industry_summary_only"


def test_general_ai_announcement_gets_medium_score(tmp_path: Path) -> None:
    article = CollectedArticle(
        title="OpenAI announces a new multimodal foundation model",
        source="OpenAI",
        url="https://example.com/general-model",
        published_date="2026-07-13",
        summary=(
            "A broad model announcement with possible effects on education, work, "
            "and information access, but limited research design details."
        ),
        category="AI研究机构",
    )

    result = evaluate_article_relevance(
        article=article,
        client=MockLLMClient(
            response=_response(
                score=5,
                categories=["数字社会", "人机交互"],
                research_question="新一代多模态模型是否改变用户的信息获取、学习和协作方式？",
                method="原文未提供明确方法；可后续设计数字痕迹数据分析或实验。",
                main_result="原文主要是产品和模型能力公告，未提供社会科学结果。",
                why_relevant_to_user="它可能启发数字社会和人机交互研究，但目前缺少可直接转化为CSS研究设计的信息。",
                research_value_score={
                    "novelty": 5,
                    "methodological_contribution": 3,
                    "relevance_to_css": 5,
                    "future_research_proposal_potential": 5,
                },
            )
        ),
        profile_path=_profile(tmp_path),
        research_profile_path=_research_profile(tmp_path),
    )

    assert result.score == 5
    assert result.decision == "short_analysis"
    assert "数字社会" in result.categories


def test_relevance_decision_thresholds_allow_more_daily_items() -> None:
    assert decision_for_score(6) == "full_research_analysis"
    assert decision_for_score(3) == "short_analysis"
    assert decision_for_score(2) == "industry_summary_only"


def _response(
    *,
    score: int,
    categories: list[str],
    research_question: str = "AI治理制度如何影响模型开发组织的问责与风险披露？",
    method: str = "结合数字痕迹数据、agent-based modeling、网络分析和政策文本分析。",
    main_result: str = "原文表明治理机制会影响前沿AI系统的评估、披露和组织实践。",
    research_value: str = "可转化为关于制度设计、组织行为和AI治理效果的计算社会科学研究。",
    why_relevant_to_user: str = "该主题直接连接用户的 AI-based CSS、AI治理和社会系统建模兴趣。",
    research_value_score: dict[str, int] | None = None,
) -> str:
    payload = {
        "score": score,
        "categories": categories,
        "research_question": research_question,
        "method": method,
        "main_result": main_result,
        "research_value": research_value,
        "research_value_score": research_value_score
        or {
            "novelty": 8,
            "methodological_contribution": 8,
            "relevance_to_css": 9,
            "future_research_proposal_potential": 9,
        },
        "why_relevant_to_user": why_relevant_to_user,
    }
    return json.dumps(payload, ensure_ascii=False)


def _profile(tmp_path: Path) -> Path:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        """
research_profile:
    background:
    - economics background
    - computational social science
    - AI-based computational social science methods
    - social simulation
    - inequality
    - AI governance
    - social systems modeling
research_keywords:
  high_priority:
    - 计算社会科学
    - AI治理
    - 算法公平
    - 人机交互
    - 社会模拟
    - AI-based CSS methods
    - LLM-based social simulation
    - Agent-based model
    - AI经济学
    - AI与劳动市场
    - AI与不平等
    - 数字社会
  medium_priority:
    - 大语言模型
    - AI Agent
    - 可解释人工智能
    - AI安全
  low_priority:
    - GPU
    - 芯片
    - 模型benchmark
    - 工程优化
""",
        encoding="utf-8",
    )
    return profile_path


def _research_profile(tmp_path: Path) -> Path:
    path = tmp_path / "research_profile.yaml"
    path.write_text(
        """
academic_background:
  - economics
  - computational social science
  - AI-based computational social science methods
  - social simulation
research_interests:
  high_priority:
    - computational social science
    - social simulation
    - AI-based CSS methods
    - LLM-based social simulation
    - agent-based modeling
    - AI governance
    - algorithmic fairness
    - human-AI interaction
    - computational sociology
  medium_priority:
    - labor economics
    - education inequality
    - digital society
  low_priority:
    - hardware
    - pure model scaling
    - benchmark-only papers
""",
        encoding="utf-8",
    )
    return path
