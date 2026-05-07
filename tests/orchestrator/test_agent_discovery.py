import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hermes_orchestrator.services.agent_discovery import (
    AgentDiscoveryService,
    CAPABILITIES_ANNOTATION,
    ROLE_ANNOTATION,
)


@pytest.fixture
def discovery():
    cfg = MagicMock()
    cfg.k8s_namespace = "hermes-agent"
    cfg.gateway_port = 8642
    cfg.agent_max_concurrent = 10
    cfg.gateway_headers = {"Authorization": "Bearer test"}
    return AgentDiscoveryService(cfg)


def _make_discovery_service() -> AgentDiscoveryService:
    """Create a bare AgentDiscoveryService without __init__."""
    svc = AgentDiscoveryService.__new__(AgentDiscoveryService)
    svc._config = MagicMock()
    svc._config.gateway_port = 8642
    svc._config.agent_max_concurrent = 10
    svc._api_key_cache = {}
    return svc


def test_build_pod_url():
    svc = _make_discovery_service()
    pod = MagicMock()
    pod.status.pod_ip = "10.244.1.42"
    url = svc._build_pod_url(pod)
    assert url == "http://10.244.1.42:8642"


def test_pod_to_profile():
    svc = _make_discovery_service()
    from datetime import datetime, timezone

    pod = MagicMock()
    pod.metadata.name = "hermes-gateway-1-abc"
    pod.status.pod_ip = "10.244.1.42"
    pod.status.phase = "Running"
    pod.metadata.creation_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = svc._pod_to_profile(pod)
    assert profile.agent_id == "hermes-gateway-1-abc"
    assert profile.gateway_url == "http://10.244.1.42:8642"
    assert profile.max_concurrent == 10
    assert profile.status == "online"


# ===================================================================
# _extract_agent_name
# ===================================================================


class TestExtractAgentName:
    """Tests for _extract_agent_name which extracts the deployment name
    from a K8s pod.  In production, ownerReferences are always present and
    used as the primary path.  The pod-name fallback is a safety net with
    known limitations for deployment names containing numeric suffixes."""

    def _make_pod_no_owner(self, name: str) -> MagicMock:
        """Create a mock pod with no ownerReferences (falls back to name parsing)."""
        pod = MagicMock()
        pod.metadata.name = name
        pod.metadata.owner_references = None
        return pod

    def _make_pod_with_owner(self, pod_name: str, rs_name: str) -> MagicMock:
        """Create a mock pod with ownerReferences pointing to a ReplicaSet."""
        pod = MagicMock()
        pod.metadata.name = pod_name
        owner = MagicMock()
        owner.name = rs_name
        pod.metadata.owner_references = [owner]
        return pod

    # --- ownerReferences path (primary, used in real K8s) ---

    def test_owner_refs_standard(self):
        """hermes-gateway-1 via ownerReferences."""
        svc = _make_discovery_service()
        pod = self._make_pod_with_owner(
            "hermes-gateway-1-abc123-xyz789", "hermes-gateway-1-abc123"
        )
        assert svc._extract_agent_name(pod) == "hermes-gateway-1"

    def test_owner_refs_multi_digit(self):
        """hermes-gateway-10 via ownerReferences."""
        svc = _make_discovery_service()
        pod = self._make_pod_with_owner(
            "hermes-gateway-10-abc123def", "hermes-gateway-10-abc123def"
        )
        assert svc._extract_agent_name(pod) == "hermes-gateway-10"

    def test_owner_refs_no_number(self):
        """hermes-gateway (no number suffix) via ownerReferences."""
        svc = _make_discovery_service()
        pod = self._make_pod_with_owner(
            "hermes-gateway-abc123-xyz", "hermes-gateway-abc123"
        )
        assert svc._extract_agent_name(pod) == "hermes-gateway"

    # --- Pod name fallback path (no ownerReferences) ---

    def test_fallback_simple_name(self):
        """hermes-gateway (no hash suffix) returns as-is."""
        svc = _make_discovery_service()
        pod = self._make_pod_no_owner("hermes-gateway")
        assert svc._extract_agent_name(pod) == "hermes-gateway"

    def test_fallback_single_hash_suffix(self):
        """hermes-gateway-abc123 has only 3 segments; rsplit('-', 2) strips 2 -> 'hermes'."""
        svc = _make_discovery_service()
        pod = self._make_pod_no_owner("hermes-gateway-abc123")
        # This is a known limitation: single-suffix names without ownerReferences
        # will lose segments. In real K8s, ownerReferences are always present.
        assert svc._extract_agent_name(pod) == "hermes"


# ===================================================================
# _parse_tags_from_annotation
# ===================================================================


class TestParseTagsFromAnnotation:
    """Tests for _parse_tags_from_annotation which extracts tag lists
    from the hermes-agent.io/capabilities annotation."""

    def test_json_array(self):
        """JSON array string is parsed into a list of lowercase tags."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: '["python", "code"]'}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python", "code"]

    def test_comma_separated(self):
        """Comma-separated string is split into individual tags."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: "python,code,testing"}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python", "code", "testing"]

    def test_empty_string(self):
        """Empty annotation value returns an empty list."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: ""}
        result = svc._parse_tags_from_annotation(ann)
        assert result == []

    def test_none_annotations(self):
        """None annotations dict returns an empty list."""
        svc = _make_discovery_service()
        result = svc._parse_tags_from_annotation(None)
        assert result == []

    def test_empty_annotations_dict(self):
        """Empty annotations dict returns an empty list."""
        svc = _make_discovery_service()
        result = svc._parse_tags_from_annotation({})
        assert result == []

    def test_missing_capability_key(self):
        """Annotations dict without the capabilities key returns empty list."""
        svc = _make_discovery_service()
        ann = {"other-annotation": "value"}
        result = svc._parse_tags_from_annotation(ann)
        assert result == []

    def test_uppercase_normalized(self):
        """Tags with uppercase letters are normalized to lowercase."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: "Python,CODE"}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python", "code"]

    def test_trailing_comma(self):
        """Trailing comma produces empty item which is filtered out."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: "python,"}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python"]

    def test_spaces_around_items(self):
        """Spaces around comma-separated items are stripped."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: " python , code "}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python", "code"]

    def test_invalid_json_fallback_to_comma(self):
        """Invalid JSON starting with '[' falls back to comma splitting."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: "[invalid"}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["[invalid"]

    def test_json_with_numbers(self):
        """JSON array with non-string items converts them via str()."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: '["python", 42]'}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python", "42"]

    def test_json_with_empty_items_filtered(self):
        """Empty strings in JSON array are filtered out."""
        svc = _make_discovery_service()
        ann = {CAPABILITIES_ANNOTATION: '["python", "", "code"]'}
        result = svc._parse_tags_from_annotation(ann)
        assert result == ["python", "code"]


# ===================================================================
# _parse_role_from_annotation
# ===================================================================


class TestParseRoleFromAnnotation:
    """Tests for _parse_role_from_annotation which extracts the agent role
    from the hermes-agent.io/role annotation."""

    def test_normal_role(self):
        """Normal role string is returned lowercase."""
        svc = _make_discovery_service()
        ann = {ROLE_ANNOTATION: "coder"}
        result = svc._parse_role_from_annotation(ann)
        assert result == "coder"

    def test_empty_returns_generalist(self):
        """Empty role string returns the default 'generalist'."""
        svc = _make_discovery_service()
        ann = {ROLE_ANNOTATION: ""}
        result = svc._parse_role_from_annotation(ann)
        assert result == "generalist"

    def test_none_returns_generalist(self):
        """None annotations returns the default 'generalist'."""
        svc = _make_discovery_service()
        result = svc._parse_role_from_annotation(None)
        assert result == "generalist"

    def test_uppercase_normalized(self):
        """Uppercase role is normalized to lowercase."""
        svc = _make_discovery_service()
        ann = {ROLE_ANNOTATION: "Coder"}
        result = svc._parse_role_from_annotation(ann)
        assert result == "coder"

    def test_missing_role_key_returns_generalist(self):
        """Annotations dict without the role key returns 'generalist'."""
        svc = _make_discovery_service()
        ann = {"other-key": "value"}
        result = svc._parse_role_from_annotation(ann)
        assert result == "generalist"

    def test_whitespace_only_returns_generalist(self):
        """Whitespace-only role returns 'generalist'."""
        svc = _make_discovery_service()
        ann = {ROLE_ANNOTATION: "   "}
        result = svc._parse_role_from_annotation(ann)
        assert result == "generalist"

    def test_role_with_leading_trailing_whitespace(self):
        """Role with surrounding whitespace is stripped."""
        svc = _make_discovery_service()
        ann = {ROLE_ANNOTATION: "  coder  "}
        result = svc._parse_role_from_annotation(ann)
        assert result == "coder"
