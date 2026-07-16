"""Computational social science research relevance filtering."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from ai_research_agent.core.config import load_research_profile
from ai_research_agent.core.errors import ResearchAgentError
from ai_research_agent.ingestion.models import CollectedArticle
from ai_research_agent.llm import LLMClient

RelevanceDecision = Literal["full_research_analysis", "short_analysis", "industry_summary_only"]

RELEVANCE_CATEGORIES = [
    "计算社会科学",
    "社会模拟",
    "AI治理",
    "AI安全",
    "算法公平",
    "人机交互",
    "AI经济学",
    "劳动市场",
    "教育不平等",
    "数字社会",
    "计算社会学",
    "硬件与基础设施",
]


@dataclass(frozen=True)
class ResearchValueScore:
    """Research intelligence dimensions behind the final relevance score."""

    novelty: int
    methodological_contribution: int
    css_relevance: int
    proposal_potential: int

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-serializable representation."""
        return {
            "novelty": self.novelty,
            "methodological_contribution": self.methodological_contribution,
            "relevance_to_css": self.css_relevance,
            "future_research_proposal_potential": self.proposal_potential,
        }


def _empty_research_value_score() -> ResearchValueScore:
    return ResearchValueScore(
        novelty=0,
        methodological_contribution=0,
        css_relevance=0,
        proposal_potential=0,
    )


@dataclass(frozen=True)
class ResearchRelevanceScore:
    """Article-level research intelligence score."""

    score: int
    categories: list[str]
    research_value: str
    decision: RelevanceDecision
    research_question: str = ""
    method: str = ""
    main_result: str = ""
    why_relevant_to_user: str = ""
    research_value_score: ResearchValueScore = field(default_factory=_empty_research_value_score)
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return the Phase 5 research-intelligence output shape."""
        return {
            "score": self.score,
            "categories": self.categories,
            "research_question": self.research_question,
            "method": self.method,
            "main_result": self.main_result,
            "research_value": self.research_value,
            "research_value_score": self.research_value_score.to_dict(),
            "why_relevant_to_user": self.why_relevant_to_user,
            "reason": self.reason or self.why_relevant_to_user,
            "decision": self.decision,
        }


def evaluate_article_relevance(
    article: CollectedArticle,
    client: LLMClient,
    profile_path: Path = Path("config/profile.yaml"),
    research_profile_path: Path = Path("config/research_profile.yaml"),
) -> ResearchRelevanceScore:
    """Evaluate whether a collected AI article is valuable for the user's research agenda."""
    profile = load_research_profile(profile_path)
    research_profile = _load_optional_research_profile(research_profile_path)
    prompt = build_relevance_prompt(
        article=article,
        profile=profile,
        research_profile=research_profile,
    )
    response = client.generate_markdown(prompt)
    return parse_relevance_response(response)


def build_relevance_prompt(
    article: CollectedArticle,
    profile: dict,
    research_profile: dict | None = None,
) -> str:
    """Build the LLM prompt for research-intelligence relevance scoring."""
    profile_yaml = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)
    research_profile_yaml = yaml.safe_dump(
        research_profile or {},
        sort_keys=False,
        allow_unicode=True,
    )
    article_json = json.dumps(article.to_dict(), ensure_ascii=False, indent=2)
    categories = "\n".join(f"- {category}" for category in RELEVANCE_CATEGORIES)

    return f"""\
你是我的个人计算社会科学（Computational Social Science, CSS）研究助理。

你的任务不是判断这条 AI 新闻是否“有趣”，而是判断它是否能转化为我的研究问题、
研究设计、理论机制或未来 proposal。

请综合两个画像：

1. 项目配置 profile.yaml，包括 research_keywords。
2. 专门的 research_profile.yaml，包括我的学术背景和研究兴趣。

用户的默认研究取向是 AI-based computational social science methods，而不是传统计量经济学。
请优先识别能启发 LLM-based social simulation、agent-based modeling、
multi-agent systems、NLP for social science、network diffusion、
platform behavior modeling 或 human-AI interaction experiments 的文章。
DID、IV、面板回归和传统因果识别只能作为辅助验证工具，不要作为高分的默认理由。

只返回 JSON，不要返回 Markdown，不要添加解释性前后缀。

JSON schema:
{{
  "score": 0-10 的整数,
  "categories": ["从允许类别中选择一个或多个"],
  "research_question": "这篇文章隐含或直接提出的研究问题；如果没有，写'原文未提供明确研究问题'",
  "method": "文章使用或暗示的方法；如果没有，写'原文未提供明确方法'",
  "main_result": "文章的主要发现或主张；如果没有，写'原文未提供明确结果'",
  "research_value": "中文解释：它的研究价值是什么",
  "research_value_score": {{
    "novelty": 0-10,
    "methodological_contribution": 0-10,
    "relevance_to_css": 0-10,
    "future_research_proposal_potential": 0-10
  }},
  "why_relevant_to_user": "中文解释：为什么它适合或不适合我的研究背景和兴趣"
}}

允许类别:
{categories}

评分逻辑:

高分文章通常满足以下条件之一：
- 直接关联 computational social science、social simulation、AI governance、
  algorithmic fairness、human-AI interaction 或 computational sociology。
- 能启发 AI-based CSS methods，包括 LLM-based social simulation、
  agent-based modeling、multi-agent systems、NLP for social science、
  network diffusion、platform behavior modeling 或 human-AI interaction experiments。
- 对社会系统建模、数字痕迹数据、组织行为、劳动市场、不平等等研究有清晰启发。
- 能形成可执行的计算建模、仿真、网络分析或 AI-assisted research design。

6-7 分文章可以进入深度分析，适用于有明确 AI-based CSS 方法启发、
但证据或原文细节还不完整的文章。

3-5 分文章通常是一般 AI 发展、产品/模型公告或 general 技术更新。
如果它能帮助用户理解 frontier AI 的能力边界、agent 能力、模型评估、
安全风险、人机交互或未来 CSS 方法工具箱，应作为短新闻保留。

0-2 分文章通常主要是 hardware、pure model scaling、benchmark-only paper、
工程优化或缺乏社会科学机制。

项目 profile.yaml:

```yaml
{profile_yaml.strip()}
```

个人 research_profile.yaml:

```yaml
{research_profile_yaml.strip()}
```

待评估文章:

```json
{article_json}
```
"""


def parse_relevance_response(response: str) -> ResearchRelevanceScore:
    """Parse and validate the LLM's JSON relevance response."""
    payload = _extract_json_object(response)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ResearchAgentError(f"Could not parse relevance response as JSON: {exc}") from exc

    score = _coerce_score(data.get("score"))
    categories = _coerce_categories(data.get("categories"))
    research_question = _required_text(data, "research_question")
    method = _required_text(data, "method")
    main_result = _required_text(data, "main_result")
    research_value = _required_text(data, "research_value")
    why_relevant_to_user = _required_text(data, "why_relevant_to_user")
    research_value_score = _coerce_research_value_score(data.get("research_value_score"))
    reason = str(data.get("reason") or why_relevant_to_user).strip()

    return ResearchRelevanceScore(
        score=score,
        categories=categories,
        research_question=research_question,
        method=method,
        main_result=main_result,
        research_value=research_value,
        why_relevant_to_user=why_relevant_to_user,
        research_value_score=research_value_score,
        decision=decision_for_score(score),
        reason=reason,
    )


def decision_for_score(score: int) -> RelevanceDecision:
    """Map a numeric relevance score to the next analysis depth."""
    if score >= 6:
        return "full_research_analysis"
    if score >= 3:
        return "short_analysis"
    return "industry_summary_only"


def _load_optional_research_profile(path: Path) -> dict:
    if not path.exists():
        return {}
    return load_research_profile(path)


def _extract_json_object(response: str) -> str:
    text = response.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ResearchAgentError("Relevance response did not contain a JSON object.")
    return text[start : end + 1]


def _coerce_score(value: object) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchAgentError("Relevance score must be an integer from 0 to 10.") from exc
    if score < 0 or score > 10:
        raise ResearchAgentError("Relevance score must be between 0 and 10.")
    return score


def _coerce_categories(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ResearchAgentError("Relevance categories must be a list.")

    categories = [str(category).strip() for category in value if str(category).strip()]
    if not categories:
        raise ResearchAgentError("Relevance response must include at least one category.")

    invalid = sorted(set(categories) - set(RELEVANCE_CATEGORIES))
    if invalid:
        allowed = ", ".join(RELEVANCE_CATEGORIES)
        raise ResearchAgentError(
            f"Unsupported relevance categories: {invalid}. Allowed categories: {allowed}"
        )
    return categories


def _coerce_research_value_score(value: object) -> ResearchValueScore:
    if not isinstance(value, dict):
        raise ResearchAgentError("research_value_score must be an object.")
    return ResearchValueScore(
        novelty=_coerce_dimension(value.get("novelty"), "novelty"),
        methodological_contribution=_coerce_dimension(
            value.get("methodological_contribution"),
            "methodological_contribution",
        ),
        css_relevance=_coerce_dimension(value.get("relevance_to_css"), "relevance_to_css"),
        proposal_potential=_coerce_dimension(
            value.get("future_research_proposal_potential"),
            "future_research_proposal_potential",
        ),
    )


def _coerce_dimension(value: object, field_name: str) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchAgentError(f"{field_name} must be an integer from 0 to 10.") from exc
    if score < 0 or score > 10:
        raise ResearchAgentError(f"{field_name} must be between 0 and 10.")
    return score


def _required_text(data: dict, key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ResearchAgentError(f"Relevance response is missing {key}.")
    return value
