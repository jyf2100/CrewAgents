import time
from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.services.agent_selector import AgentSelector

def _agent(agent_id: str, load: int = 0, status: str = "online", circuit_state: str = "closed") -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        gateway_url=f"http://{agent_id}:8642",
        registered_at=time.time(),
        current_load=load,
        status=status,
        circuit_state=circuit_state,
    )

def test_selects_lowest_load():
    selector = AgentSelector()
    agents = [_agent("a1", load=3), _agent("a2", load=1), _agent("a3", load=5)]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_excludes_offline():
    selector = AgentSelector()
    agents = [_agent("a1", status="offline"), _agent("a2", status="online")]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_excludes_full_load():
    selector = AgentSelector()
    agents = [_agent("a1", load=10), _agent("a2", load=2)]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_excludes_open_circuit():
    selector = AgentSelector()
    agents = [_agent("a1", circuit_state="open"), _agent("a2", circuit_state="closed")]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_returns_none_when_all_excluded():
    selector = AgentSelector()
    agents = [_agent("a1", status="offline"), _agent("a2", circuit_state="open"), _agent("a3", load=10)]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    assert selector.select(agents, task) is None

def test_returns_none_empty_list():
    selector = AgentSelector()
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    assert selector.select([], task) is None
