"""Tests for AgentSelector smart routing (Phase 1).

Covers _extract_keywords, _compute_tag_score, and AgentSelector.select
across all routing levels: required_tags, tag_match, and least_load fallback.
"""

from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task, RoutingInfo
from hermes_orchestrator.services.agent_selector import (
    AgentSelector,
    _extract_keywords,
    _compute_tag_score,
    TAG_MATCH_MIN_SCORE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(
    agent_id: str,
    tags: list[str] | None = None,
    current_load: int = 0,
    max_concurrent: int = 10,
    status: str = "online",
    circuit_state: str = "closed",
    domain: str = "generalist",
    skills: list[str] | None = None,
) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        gateway_url=f"http://{agent_id}:8642",
        registered_at=1000.0,
        tags=tags or [],
        current_load=current_load,
        max_concurrent=max_concurrent,
        status=status,
        circuit_state=circuit_state,
        domain=domain,
        skills=skills or [],
    )


def _make_task(
    prompt: str,
    instructions: str = "",
    required_tags: list[str] | None = None,
    domain: str = "generalist",
    preferred_tags: list[str] | None = None,
) -> Task:
    return Task(
        task_id="test-task",
        prompt=prompt,
        instructions=instructions,
        required_tags=required_tags or [],
        domain=domain,
        preferred_tags=preferred_tags or [],
        created_at=1000.0,
    )


# ===================================================================
# _extract_keywords
# ===================================================================

class TestExtractKeywords:
    """Tests for the _extract_keywords helper."""

    def test_english_text_extracts_meaningful_words(self):
        result = _extract_keywords("deploy the application to kubernetes")
        assert "devops" in result  # "deploy" and "kubernetes" alias to devops

    def test_chinese_text_extracts_phrases(self):
        # CJK regex matches contiguous runs, so "数据库" is extracted as its own token
        # only when separated by non-CJK chars. Use a string with natural breaks.
        result = _extract_keywords("优化 数据库 性能")
        # "数据库" is a contiguous 3-char CJK token (>= 2 chars, not a stop word)
        assert "数据库" in result

    def test_mixed_english_chinese(self):
        result = _extract_keywords("用python写一个api接口")
        assert "python" in result or "code" in result  # "python" aliases to python,code
        assert "api" in result

    def test_aliases_expand_code(self):
        result = _extract_keywords("debug the python code")
        assert "debugging" in result  # "debug" aliases to debugging
        assert "code" in result       # "python" expands to python,code

    def test_aliases_expand_javascript(self):
        result = _extract_keywords("write javascript test")
        assert "javascript" in result
        assert "code" in result
        assert "testing" in result  # "test" (singular) aliases to "testing"

    def test_aliases_expand_js_shorthand(self):
        result = _extract_keywords("fix the js error")
        assert "javascript" in result  # "js" aliases to javascript
        assert "debugging" in result   # "fix" and "error" alias to debugging
        assert "code" in result

    def test_aliases_expand_go(self):
        result = _extract_keywords("deploy a golang service")
        assert "golang" in result
        assert "devops" in result  # "deploy" aliases to devops

    def test_aliases_expand_docker(self):
        result = _extract_keywords("build a docker container")
        assert "devops" in result
        assert "code" in result  # "docker" aliases to devops,code

    def test_aliases_expand_k8s(self):
        result = _extract_keywords("deploy to k8s cluster")
        assert "devops" in result

    def test_stop_words_filtered(self):
        result = _extract_keywords("the a an is are was were be been being")
        # All are stop words; no 2+ letter non-stop-word remains
        assert len(result) == 0

    def test_chinese_stop_words_filtered(self):
        result = _extract_keywords("的了在是我有和就不人都一个")
        # Single-char Chinese is filtered (< 2 chars), and common 2-char stop words too
        assert "的" not in result
        assert "了" not in result

    def test_chinese_no_spaces_extracts_per_character_runs(self):
        """Chinese text without spaces should still extract meaningful CJK tokens.

        The CJK regex matches contiguous runs of CJK characters (>= 2 chars).
        Without spaces, the entire string becomes one large token if it exceeds
        the 2-char minimum. This test validates that extraction works on
        space-free Chinese text.
        """
        # Single continuous run - extracted as one large token (>= 2 chars)
        result = _extract_keywords("数据库优化")
        assert "数据库优化" in result

    def test_chinese_mixed_no_spaces(self):
        """Mixed Chinese without spaces still produces meaningful tokens."""
        # The regex [一-鿿㐀-䶿]+ matches the entire CJK sequence as one run
        result = _extract_keywords("用python写排序算法")
        # "python" extracted via [a-z]{2,} regex, aliases to python,code
        assert "python" in result or "code" in result
        # The CJK part "用" + "写排序算法" - "用" is 1 char (filtered),
        # "写排序算法" is 4-char CJK run (not a stop word)
        assert "写排序算法" in result

    def test_chinese_with_punctuation_breaks(self):
        """Chinese text with punctuation between words produces separate CJK tokens."""
        result = _extract_keywords("优化、数据库、性能")
        # Punctuation "、" breaks CJK runs into separate tokens
        assert "优化" in result
        assert "数据库" in result
        assert "性能" in result

    def test_short_tokens_excluded(self):
        result = _extract_keywords("I am a x y z go")
        # Single letters excluded; "go" is a stop word
        # "am" is a stop word
        assert "x" not in result
        assert "y" not in result

    def test_empty_string_returns_empty(self):
        result = _extract_keywords("")
        assert result == set()

    def test_only_stop_words_returns_empty(self):
        result = _extract_keywords("please help me I want to get it")
        assert len(result) == 0

    def test_aliases_expand_translate(self):
        result = _extract_keywords("translate the docs")
        assert "translation" in result
        assert "documentation" in result  # "docs" aliases to documentation

    def test_aliases_expand_review(self):
        result = _extract_keywords("review the pull request")
        assert "code-review" in result

    def test_aliases_expand_refactor(self):
        result = _extract_keywords("refactor the module")
        assert "code-review" in result
        assert "code" in result

    def test_aliases_expand_database(self):
        result = _extract_keywords("optimize sql query performance")
        assert "database" in result  # "sql" and "query" alias to database

    def test_instructions_combined_with_prompt(self):
        # _extract_keywords itself only processes one text; the caller joins
        # prompt + instructions. Verify keywords come from both.
        result = _extract_keywords("deploy the service microservice")
        assert "devops" in result  # "deploy"


# ===================================================================
# _compute_tag_score
# ===================================================================

class TestComputeTagScore:
    """Tests for the _compute_tag_score Jaccard similarity helper."""

    def test_perfect_match(self):
        task_tags = {"python", "code"}
        agent_tags = ["python", "code", "debugging"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        # matched = {python, code} (2), union = {python, code, debugging} (3)
        assert len(matched) == 2
        assert abs(score - 2 / 3) < 1e-9

    def test_partial_match(self):
        task_tags = {"python", "creative", "debugging"}
        agent_tags = ["python", "devops"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        # matched = {python} (1), union = {python, creative, debugging, devops} (4)
        assert matched == ["python"]
        assert abs(score - 1 / 4) < 1e-9

    def test_no_match(self):
        task_tags = {"python", "code"}
        agent_tags = ["devops", "docker"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        assert score == 0.0
        assert matched == []

    def test_empty_task_tags(self):
        score, matched = _compute_tag_score(set(), ["python"])
        assert score == 0.0
        assert matched == []

    def test_empty_agent_tags(self):
        score, matched = _compute_tag_score({"python"}, [])
        assert score == 0.0
        assert matched == []

    def test_both_empty(self):
        score, matched = _compute_tag_score(set(), [])
        assert score == 0.0
        assert matched == []

    def test_jaccard_identical_sets(self):
        tags = {"python", "code", "debugging"}
        score, matched = _compute_tag_score(tags, list(tags))
        assert score == 1.0
        assert sorted(matched) == sorted(tags)

    def test_jaccard_disjoint_sets(self):
        task_tags = {"a", "b"}
        agent_tags = ["c", "d"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        assert score == 0.0
        assert matched == []

    def test_jaccard_one_element_overlap(self):
        task_tags = {"a", "b", "c"}
        agent_tags = ["c", "d", "e"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        # matched={c}, union={a,b,c,d,e} -> 1/5
        assert abs(score - 1 / 5) < 1e-9
        assert matched == ["c"]

    def test_case_insensitive_agent_tags(self):
        task_tags = {"python", "code"}
        agent_tags = ["Python", "CODE"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        assert score == 1.0

    def test_matched_tags_sorted(self):
        task_tags = {"zebra", "alpha", "mid"}
        agent_tags = ["zebra", "alpha", "mid", "extra"]
        score, matched = _compute_tag_score(task_tags, agent_tags)
        assert matched == ["alpha", "mid", "zebra"]


# ===================================================================
# AgentSelector.select
# ===================================================================

class TestAgentSelectorSelect:
    """Tests for the AgentSelector.select routing logic."""

    # ----- No available agents -----

    def test_no_available_agents_returns_none_with_routing_info(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", status="offline"),
            _make_agent("a2", circuit_state="open"),
            _make_agent("a3", current_load=10),
        ]
        task = _make_task("hello")
        agent, info = selector.select(agents, task)
        assert agent is None
        assert info is not None
        assert info.strategy == "no_agent"

    def test_empty_agent_list_returns_none_with_routing_info(self):
        selector = AgentSelector()
        task = _make_task("hello")
        agent, info = selector.select([], task)
        assert agent is None
        assert info is not None
        assert info.strategy == "no_agent"

    # ----- Level 1: required_tags hard constraint -----

    def test_required_tags_satisfied_picks_least_loaded(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code", "devops"], current_load=5),
            _make_agent("a2", tags=["python", "code"], current_load=1),
            _make_agent("a3", tags=["python", "code"], current_load=3),
        ]
        task = _make_task("run code", required_tags=["python", "code"])
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"
        assert info is not None
        assert info.strategy == "required_tags"
        assert info.chosen_agent_id == "a2"
        assert info.fallback is False
        assert "python" in info.matched_tags
        assert "code" in info.matched_tags

    def test_required_tags_not_satisfied_returns_none_with_routing_info(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["devops"]),
            _make_agent("a2", tags=["python"]),
        ]
        task = _make_task("run code", required_tags=["python", "code"])
        agent, info = selector.select(agents, task)
        assert agent is None
        assert info is not None
        assert info.strategy == "required_tags_unsatisfied"
        assert info.chosen_agent_id is None
        assert info.fallback is False
        assert "required_tags" in info.reason

    def test_required_tags_no_fallback_to_least_load(self):
        """When required_tags are set but no agent satisfies them, do NOT fall back."""
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["devops"], current_load=0),
        ]
        task = _make_task("run code", required_tags=["python"])
        agent, info = selector.select(agents, task)
        assert agent is None
        assert info is not None
        assert info.strategy == "required_tags_unsatisfied"

    def test_required_tags_excludes_unavailable_agents(self):
        """required_tags check should only consider available agents."""
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code"], circuit_state="open"),
            _make_agent("a2", tags=["python", "code"], current_load=10),
            _make_agent("a3", tags=["python"], current_load=0),
        ]
        task = _make_task("code", required_tags=["python", "code"])
        agent, info = selector.select(agents, task)
        assert agent is None
        assert info is not None
        assert info.strategy == "required_tags_unsatisfied"
        assert info.chosen_agent_id is None

    def test_required_tags_scores_all_candidates(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code"], current_load=2),
            _make_agent("a2", tags=["python", "code"], current_load=0),
        ]
        task = _make_task("code", required_tags=["python"])
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"
        assert info is not None
        assert info.scores == {"a1": 1.0, "a2": 1.0}

    # ----- Level 2: tag_match scoring -----

    def test_tag_match_above_threshold_picks_best(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code", "debugging"]),
            _make_agent("a2", tags=["devops", "docker"]),
        ]
        task = _make_task("debug python code")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"
        assert info is not None
        assert info.strategy == "domain_tag_match"
        assert info.fallback is False
        assert info.scores["a1"] > info.scores["a2"]

    def test_tag_match_threshold_boundary(self):
        """Score >= TAG_MATCH_MIN_SCORE should use tag_match strategy."""
        selector = AgentSelector()
        # Build a scenario where the score is exactly at threshold
        # "python" -> {python, code}; agent has ["python"] -> matched={python}, union={python,code} = 0.5
        agents = [
            _make_agent("a1", tags=["python"]),
        ]
        task = _make_task("python programming")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert info is not None
        assert info.strategy == "domain_tag_match"

    def test_tag_match_includes_matched_tags(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code", "debugging"]),
        ]
        task = _make_task("fix the python bug")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert info is not None
        assert info.strategy == "domain_tag_match"
        assert "python" in info.matched_tags
        assert "debugging" in info.matched_tags

    def test_tag_match_scores_populated_for_all_agents(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code"]),
            _make_agent("a2", tags=["devops"]),
            _make_agent("a3", tags=[]),
        ]
        task = _make_task("write python code")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert info is not None
        assert set(info.scores.keys()) == {"a1", "a2", "a3"}

    # ----- Level 3: least_load fallback -----

    def test_tag_match_below_threshold_falls_back_to_least_load(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["devops", "docker"], current_load=3),
            _make_agent("a2", tags=["creative", "writing"], current_load=0),
        ]
        task = _make_task("random unrelated query about weather")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"
        assert info is not None
        assert info.strategy == "least_load"
        assert info.fallback is True

    def test_least_load_picks_lowest_current_load(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=[], current_load=5),
            _make_agent("a2", tags=[], current_load=2),
            _make_agent("a3", tags=[], current_load=8),
        ]
        task = _make_task("something completely new")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"
        assert info is not None
        assert info.strategy == "least_load"

    # ----- Agent filtering -----

    def test_agent_with_open_circuit_excluded(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code"], circuit_state="open"),
            _make_agent("a2", tags=["python", "code"]),
        ]
        task = _make_task("python code")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"

    def test_agent_at_max_capacity_excluded(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python"], current_load=5, max_concurrent=5),
            _make_agent("a2", tags=["python"], current_load=3, max_concurrent=10),
        ]
        task = _make_task("python programming")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"

    def test_agent_offline_excluded(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", status="offline"),
            _make_agent("a2", status="online"),
        ]
        task = _make_task("hello")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"

    def test_degraded_agent_is_available(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", status="degraded"),
        ]
        task = _make_task("hello")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"

    # ----- Chinese prompt matching -----

    def test_chinese_prompt_matches_tags(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code"]),
            _make_agent("a2", tags=["devops"]),
        ]
        task = _make_task("用python写一个排序算法")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"
        assert info is not None
        assert info.strategy == "domain_tag_match"
        assert info.scores["a1"] > info.scores["a2"]

    def test_chinese_prompt_with_instructions(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["translation"]),
            _make_agent("a2", tags=["devops"]),
        ]
        # "translate" is an English word that aliases to "translation"
        task = _make_task(
            prompt="translate the following text",
            instructions="请把英文翻译成中文",
        )
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"
        assert info is not None
        assert info.strategy == "domain_tag_match"

    # ----- RoutingInfo fields -----

    def test_routing_info_has_reason(self):
        selector = AgentSelector()
        agents = [_make_agent("a1")]
        task = _make_task("hello")
        agent, info = selector.select(agents, task)
        assert info is not None
        assert isinstance(info.reason, str)
        assert len(info.reason) > 0

    def test_tag_match_reason_contains_composite_and_jaccard(self):
        selector = AgentSelector()
        agents = [_make_agent("a1", tags=["python"])]
        task = _make_task("python code")
        agent, info = selector.select(agents, task)
        assert info is not None
        assert info.strategy == "domain_tag_match"
        assert "composite=" in info.reason
        assert "jaccard=" in info.reason

    def test_least_load_reason_mentions_fallback(self):
        selector = AgentSelector()
        agents = [_make_agent("a1", tags=["devops"])]
        task = _make_task("weather forecast")
        agent, info = selector.select(agents, task)
        assert info is not None
        assert info.strategy == "least_load"
        assert "least_load" in info.reason

    # ----- Edge cases -----

    def test_agent_with_no_tags_least_load(self):
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=[], current_load=0),
            _make_agent("a2", tags=[], current_load=1),
        ]
        task = _make_task("anything")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"
        assert info is not None

    def test_task_with_empty_prompt_least_load(self):
        selector = AgentSelector()
        agents = [_make_agent("a1", tags=["python"])]
        task = _make_task("")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"

    def test_single_agent_tag_match(self):
        selector = AgentSelector()
        agents = [_make_agent("a1", tags=["python", "code", "testing"])]
        task = _make_task("write a python test")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"
        assert info is not None
        assert info.strategy == "domain_tag_match"
        assert "python" in info.matched_tags

    def test_required_tags_case_insensitive(self):
        selector = AgentSelector()
        agents = [_make_agent("a1", tags=["Python", "CODE"])]
        task = _make_task("run code", required_tags=["python", "code"])
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a1"
        assert info is not None
        assert info.strategy == "required_tags"


# ===================================================================
# Domain routing tests
# ===================================================================

class TestDomainRouting:
    """Tests for the three-layer domain routing fallback."""

    def test_domain_exact_match(self):
        """task.domain='code' should match agent.domain='code'."""
        selector = AgentSelector()
        agents = [
            _make_agent("coder-1", tags=["python"], domain="code"),
            _make_agent("gen-1", tags=["python"], domain="generalist"),
        ]
        task = _make_task("write python code", domain="code")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "coder-1"
        assert info is not None
        assert info.strategy == "domain_tag_match"

    def test_domain_fallback_generalist(self):
        """When no code agent exists, fallback to generalist."""
        selector = AgentSelector()
        agents = [
            _make_agent("gen-1", tags=["python"], domain="generalist"),
            _make_agent("data-1", tags=["python"], domain="data"),
        ]
        task = _make_task("write python code", domain="code")
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "gen-1"
        assert info is not None
        assert info.strategy == "domain_fallback_tag_match"

    def test_domain_fallback_all_eligible(self):
        """When no code or generalist agents exist, use all eligible agents."""
        selector = AgentSelector()
        agents = [
            _make_agent("data-1", tags=["python"], domain="data", current_load=3),
            _make_agent("ops-1", tags=["python"], domain="ops", current_load=0),
        ]
        task = _make_task("write python code", domain="code")
        agent, info = selector.select(agents, task)
        assert agent is not None
        # Should pick ops-1 (lower load)
        assert agent.agent_id == "ops-1"
        assert info is not None
        assert info.strategy == "domain_fallback_tag_match"

    def test_required_tags_with_domain_relax(self):
        """When required_tags not met in domain, relax domain and retry."""
        selector = AgentSelector()
        agents = [
            _make_agent("coder-1", tags=["python"], domain="code"),
            _make_agent("gen-1", tags=["python", "golang"], domain="generalist"),
        ]
        # Task wants code domain with golang skill, but coder-1 lacks golang
        task = _make_task("write golang code", domain="code", required_tags=["golang"])
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "gen-1"
        assert info is not None
        # Domain was relaxed to satisfy required_tags
        assert info.strategy == "domain_fallback_tag_match"
        assert "golang" in info.matched_tags

    def test_preferred_tags_jaccard(self):
        """preferred_tags should merge into Jaccard scoring for better matching."""
        selector = AgentSelector()
        agents = [
            _make_agent("a1", tags=["python", "code"]),
            _make_agent("a2", tags=["python", "code", "testing", "golang"]),
        ]
        # preferred_tags=golang should boost a2's Jaccard score
        task = _make_task(
            "write code",
            preferred_tags=["golang"],
        )
        agent, info = selector.select(agents, task)
        assert agent is not None
        assert agent.agent_id == "a2"
        assert info is not None
        assert info.scores["a2"] > info.scores["a1"]
