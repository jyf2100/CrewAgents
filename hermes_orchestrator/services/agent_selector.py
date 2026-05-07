from __future__ import annotations

import logging
import math
import re

from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.api import RoutingStrategy
from hermes_orchestrator.models.task import Task, RoutingInfo

logger = logging.getLogger(__name__)

TAG_MATCH_MIN_SCORE = 0.15

# Transitional mapping: role -> domain (Phase A compatibility)
ROLE_TO_DOMAIN: dict[str, str] = {
    "generalist": "generalist",
    "coder": "code",
    "analyst": "data",
    "devops": "ops",
    "sre": "ops",
    "writer": "creative",
    "translator": "creative",
    "designer": "creative",
}

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "about", "up", "it", "its", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "this", "that", "these", "those", "what", "which",
    "who", "whom", "please", "help", "need", "want", "make", "like",
    "get", "got", "go", "going", "come", "take", "give", "tell",
    "say", "said", "know", "think", "see", "look", "find", "use",
    "try", "ask", "put", "keep", "let", "begin", "seem", "show",
    "hear", "play", "run", "move", "live", "believe", "happen",
    "also", "back", "still", "even", "much", "well", "really",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
    "它", "们", "那", "些", "什么", "怎么", "可以", "能", "把",
    "被", "让", "给", "对", "与", "从", "以", "为", "之", "中",
})

_TAG_ALIASES: dict[str, list[str]] = {
    "python": ["python", "code"],
    "javascript": ["javascript", "code"],
    "js": ["javascript", "code"],
    "typescript": ["typescript", "code"],
    "ts": ["typescript", "code"],
    "java": ["java", "code"],
    "go": ["golang", "code"],
    "golang": ["golang", "code"],
    "rust": ["rust", "code"],
    "code": ["code"],
    "coding": ["code"],
    "program": ["code"],
    "programming": ["code"],
    "debug": ["debugging"],
    "debugging": ["debugging"],
    "fix": ["debugging"],
    "bug": ["debugging"],
    "error": ["debugging"],
    "analyze": ["analysis"],
    "analysis": ["analysis"],
    "data": ["analysis"],
    "chart": ["analysis"],
    "graph": ["analysis"],
    "write": ["creative"],
    "article": ["creative"],
    "blog": ["creative"],
    "story": ["creative"],
    "creative": ["creative"],
    "translate": ["translation"],
    "translation": ["translation"],
    "explain": ["explanation"],
    "documentation": ["documentation"],
    "docs": ["documentation"],
    "search": ["search"],
    "research": ["research"],
    "deploy": ["devops"],
    "deployment": ["devops"],
    "docker": ["devops", "code"],
    "kubernetes": ["devops"],
    "k8s": ["devops"],
    "devops": ["devops"],
    "test": ["testing"],
    "testing": ["testing"],
    "review": ["code-review"],
    "refactor": ["code-review", "code"],
    "database": ["database"],
    "sql": ["database"],
    "query": ["database"],
    "api": ["api"],
    "rest": ["api"],
    "grpc": ["api"],
    "翻译": ["translation"],
    "数据库": ["database"],
    "数据": ["database"],
    "性能": ["analysis"],
    "优化": ["analysis"],
    "部署": ["devops"],
    "测试": ["testing"],
    "文档": ["documentation"],
    "搜索": ["search"],
    "研究": ["research"],
    "调试": ["debugging"],
    "分析": ["analysis"],
    "代码": ["code"],
    "编程": ["code"],
    "接口": ["api"],
}

# CJK unified ideograph ranges
_CJK_PATTERN = re.compile(r"[一-鿿㐀-䶿]+")


def _extract_keywords(text: str) -> set[str]:
    text_lower = text.lower()
    words: set[str] = set()
    for w in re.findall(r"[a-z]{2,}", text_lower):
        if w not in _STOP_WORDS and len(w) > 1:
            words.add(w)
    # CJK: extract contiguous runs (phrases) and also extract
    # 2-char substrings (bigrams) for alias expansion.  The bigrams
    # themselves are NOT added to the word set (to avoid diluting Jaccard
    # scores), but their alias expansions ARE added.  This means "数据库"
    # inside "优化数据库性能" expands to ["database"] via aliases.
    for match in _CJK_PATTERN.finditer(text_lower):
        cjk_run = match.group()
        if len(cjk_run) >= 2 and cjk_run not in _STOP_WORDS:
            words.add(cjk_run)
        if len(cjk_run) > 2:
            for i in range(len(cjk_run) - 1):
                bigram = cjk_run[i:i + 2]
                if bigram not in _STOP_WORDS and bigram in _TAG_ALIASES:
                    words.update(_TAG_ALIASES[bigram])
    expanded: set[str] = set()
    for w in words:
        if w in _TAG_ALIASES:
            expanded.update(_TAG_ALIASES[w])
            # Also keep the original word so it can match agent tags directly
            expanded.add(w)
        else:
            expanded.add(w)
    return expanded


def _compute_tag_score(
    task_tags: set[str],
    agent_tags: list[str],
) -> tuple[float, list[str]]:
    if not task_tags or not agent_tags:
        return 0.0, []
    agent_tag_set = {t.lower() for t in agent_tags}
    matched = task_tags & agent_tag_set
    if not matched:
        return 0.0, []
    union = task_tags | agent_tag_set
    score = len(matched) / len(union)
    return score, sorted(matched)


def _get_agent_domain(agent: AgentProfile) -> str:
    """Get the effective domain for an agent. During transition, falls back to role mapping."""
    if agent.domain and agent.domain != "generalist":
        return agent.domain
    # Transitional fallback: map role -> domain
    return ROLE_TO_DOMAIN.get(agent.role, agent.domain or "generalist")


def _compute_health_score(agent: AgentProfile) -> float:
    """Compute health score: online=1.0, degraded=0.5, half_open gets 0.7 multiplier."""
    if agent.status == "online":
        base = 1.0
    elif agent.status == "degraded":
        base = 0.5
    else:
        base = 0.0
    if agent.circuit_state == "half_open":
        base *= 0.7
    return base


class AgentSelector:
    """Three-phase routing selector implementing Domain + Skills design.

    Phase 1: Domain hard constraint (three-layer fallback)
    Phase 2: required_tags hard constraint (with domain relaxation)
    Phase 3: Weighted scoring: 0.50 * jaccard + 0.35 * load_score + 0.15 * health
    """

    # Scoring weights
    W_JACCARD = 0.50
    W_LOAD = 0.35
    W_HEALTH = 0.15

    def select(
        self, agents: list[AgentProfile], task: Task
    ) -> tuple[AgentProfile | None, RoutingInfo | None]:
        # --- Pre-filter: exclude unavailable agents ---
        eligible = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.circuit_state != "open"
            and a.current_load < a.max_concurrent
        ]

        if not eligible:
            # Try half_open agents as last resort
            half_open = [
                a for a in agents
                if a.status in ("online", "degraded")
                and a.circuit_state == "half_open"
                and a.current_load < a.max_concurrent
            ]
            if half_open:
                eligible = half_open
            else:
                logger.warning(
                    "No available agent for task %s (checked %d agents)",
                    task.task_id, len(agents),
                )
                return None, RoutingInfo(
                    strategy=RoutingStrategy.NO_AGENT,
                    chosen_agent_id=None,
                    scores={},
                    matched_tags=[],
                    fallback=False,
                    reason=f"No available agent (checked {len(agents)} agents)",
                )

        # --- Phase 1: Domain hard constraint ---
        task_domain = getattr(task, "domain", "generalist") or "generalist"
        domain_agents = [a for a in eligible if _get_agent_domain(a) == task_domain]
        domain_fallback = False

        if not domain_agents:
            # Fallback L1: try generalist agents
            domain_agents = [a for a in eligible if _get_agent_domain(a) == "generalist"]
            domain_fallback = True

        if not domain_agents:
            # Fallback L2: use all eligible agents
            domain_agents = eligible
            domain_fallback = True

        # --- Phase 2: required_tags hard constraint ---
        if task.required_tags:
            required_set = {t.lower() for t in task.required_tags}
            # Transitional: check both skills and tags
            filtered = [
                a for a in domain_agents
                if required_set <= {t.lower() for t in (list(a.skills) + list(a.tags))}
            ]
            if filtered:
                domain_agents = filtered
            else:
                # Relax domain constraint and retry
                wider = [
                    a for a in eligible
                    if required_set <= {t.lower() for t in (list(a.skills) + list(a.tags))}
                ]
                if wider:
                    domain_agents = wider
                    domain_fallback = True
                else:
                    # required_tags cannot be satisfied -> requeue instead of marking failed
                    logger.warning(
                        "Task %s required_tags %s not satisfied by any agent",
                        task.task_id, task.required_tags,
                    )
                    return None, RoutingInfo(
                        strategy=RoutingStrategy.REQUIRED_TAGS_UNSATISFIED,
                        chosen_agent_id=None,
                        scores={},
                        matched_tags=[],
                        fallback=False,
                        reason=f"No agent satisfies required_tags: {task.required_tags}",
                        requeue=True,
                    )

        # --- Phase 3: Weighted scoring ---
        source_text = f"{task.prompt} {task.instructions}"
        task_keywords = _extract_keywords(source_text)
        soft_tags = (
            task_keywords
            | {t.lower() for t in task.required_tags}
            | {t.lower() for t in getattr(task, "preferred_tags", [])}
        )

        scores: dict[str, float] = {}
        matched_tags_map: dict[str, list[str]] = {}
        composites: dict[str, float] = {}

        for a in domain_agents:
            # Transitional: combine skills + tags for Jaccard
            jaccard_score, matched = _compute_tag_score(soft_tags, list(a.skills) + list(a.tags))
            load_pct = a.current_load / a.max_concurrent if a.max_concurrent > 0 else 1.0
            load_score = math.exp(-2.0 * load_pct)
            health_score = _compute_health_score(a)

            composite = (
                self.W_JACCARD * jaccard_score
                + self.W_LOAD * load_score
                + self.W_HEALTH * health_score
            )

            scores[a.agent_id] = jaccard_score
            matched_tags_map[a.agent_id] = matched
            composites[a.agent_id] = composite

        # Sort: composite desc, load asc, registered_at asc (deterministic ordering)
        domain_agents.sort(
            key=lambda a: (
                -composites[a.agent_id],
                a.current_load / a.max_concurrent if a.max_concurrent > 0 else 1.0,
                a.registered_at,
            )
        )

        chosen = domain_agents[0]
        best_composite = composites[chosen.agent_id]
        best_jaccard = scores[chosen.agent_id]

        # Determine strategy name for RoutingInfo
        if task.required_tags:
            if domain_fallback:
                strategy = RoutingStrategy.DOMAIN_FALLBACK_TAG_MATCH
            else:
                strategy = RoutingStrategy.REQUIRED_TAGS
        elif best_jaccard >= TAG_MATCH_MIN_SCORE:
            if domain_fallback:
                strategy = RoutingStrategy.DOMAIN_FALLBACK_TAG_MATCH
            else:
                strategy = RoutingStrategy.DOMAIN_TAG_MATCH
        else:
            strategy = RoutingStrategy.LEAST_LOAD

        return chosen, RoutingInfo(
            strategy=strategy,
            chosen_agent_id=chosen.agent_id,
            scores=scores,
            matched_tags=matched_tags_map[chosen.agent_id],
            fallback=(strategy == RoutingStrategy.LEAST_LOAD),
            reason=self._build_reason(
                strategy, chosen, best_composite, best_jaccard, domain_fallback,
            ),
        )

    def _build_reason(
        self,
        strategy: RoutingStrategy,
        chosen: AgentProfile,
        composite: float,
        jaccard: float,
        domain_fallback: bool,
    ) -> str:
        if strategy == RoutingStrategy.DOMAIN_TAG_MATCH:
            return (
                f"Domain tag match, composite={composite:.3f}, "
                f"jaccard={jaccard:.3f}, agent {chosen.agent_id}"
            )
        if strategy == RoutingStrategy.DOMAIN_FALLBACK_TAG_MATCH:
            return (
                f"Domain fallback tag match, composite={composite:.3f}, "
                f"jaccard={jaccard:.3f}, agent {chosen.agent_id}"
            )
        if strategy == RoutingStrategy.REQUIRED_TAGS:
            return (
                f"Required tags matched, composite={composite:.3f}, "
                f"selected {chosen.agent_id}"
            )
        # LEAST_LOAD
        return (
            f"Tag match score {jaccard:.3f} < threshold {TAG_MATCH_MIN_SCORE}, "
            f"fell back to least_load, agent {chosen.agent_id}"
        )
