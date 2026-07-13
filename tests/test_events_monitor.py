from hark.events import make_agent_status_event, make_watch_armed, monitor_profile
from hark.herdr.client import AgentInfo


def test_watch_armed_monitor():
    e = make_watch_armed(["local"], transport="poll", statuses=["blocked", "done"])
    m = monitor_profile(e)
    assert m["kind"] == "watch.armed"
    assert m["event_id"]
    assert "sessions" in m


def test_blocked_monitor_compact():
    agent = AgentInfo(
        session_id="local",
        pane_id="w1:p6",
        agent="claude",
        status="blocked",
        revision=3,
        workspace_id="w1",
        tab_id="w1:t1",
    )
    e = make_agent_status_event(
        agent,
        from_status="working",
        to_status="blocked",
        question_text="Allow running something?",
    )
    m = monitor_profile(e)
    assert m["kind"] == "agent.blocked"
    assert m["pane_id"] == "w1:p6"
    assert "event_id" in m
    assert "instructions" in m
    assert "invent" in m["instructions"].lower()
