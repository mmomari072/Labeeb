import json
import time
from pathlib import Path
import pytest

from labeeb.execution import ExecutionEvent
from labeeb.publisher import (
    EventPublisher,
    JsonlEventPublisher,
    NullEventPublisher,
    CompositeEventPublisher,
    LiveObserver,
    PublisherError,
)
from labeeb.campaign import Campaign, CampaignManifest


def test_null_event_publisher():
    pub = NullEventPublisher()
    assert not pub.enabled
    # publish should be a complete no-op and never raise
    pub.publish({"event_type": "test", "data": 123})
    assert len(pub.get_buffered_events()) == 0


def test_jsonl_event_publisher_basic(tmp_path: Path):
    event_file = tmp_path / "events.jsonl"
    pub = JsonlEventPublisher(event_file)
    assert pub.enabled

    pub.publish({"event_type": "case_start", "case_id": 0, "status": "STARTED"})
    pub.publish(
        ExecutionEvent(
            command="mcnp6 i=input",
            cwd=str(tmp_path),
            status="SUCCESS",
            returncode=0,
            duration_seconds=1.5,
            started_at="2026-09-02T00:00:00Z",
            ended_at="2026-09-02T00:00:01.5Z",
            case_id=0,
            unit="mcnp",
            attempt=1,
        )
    )
    pub.flush()

    assert event_file.exists()
    lines = event_file.read_text().strip().split("\n")
    assert len(lines) == 2

    e0 = json.loads(lines[0])
    assert e0["event_type"] == "case_start"
    assert e0["case_id"] == 0

    e1 = json.loads(lines[1])
    assert e1["unit"] == "mcnp"
    assert e1["status"] == "SUCCESS"
    assert e1["duration_seconds"] == 1.5


def test_publisher_disabled_mode(tmp_path: Path):
    event_file = tmp_path / "events.jsonl"
    pub = JsonlEventPublisher(event_file, enabled=False)
    assert not pub.enabled

    pub.publish({"event_type": "case_start", "case_id": 0})
    pub.flush()

    assert not event_file.exists()
    assert len(pub.get_buffered_events()) == 0


def test_publisher_redaction(tmp_path: Path):
    event_file = tmp_path / "events_redacted.jsonl"
    pub = JsonlEventPublisher(
        event_file,
        redact_keys=["password", "secret_token", "api_key"]
    )

    pub.publish({
        "event_type": "auth",
        "user": "omari",
        "password": "supersecretpassword",
        "nested": {"api_key": "12345-abcde", "public": "visible"}
    })
    pub.flush()

    record = json.loads(event_file.read_text().strip())
    assert record["user"] == "omari"
    assert record["password"] == "[REDACTED]"
    assert record["nested"]["api_key"] == "[REDACTED]"
    assert record["nested"]["public"] == "visible"


def test_publisher_buffering_and_replay(tmp_path: Path):
    event_file = tmp_path / "events.jsonl"
    pub = JsonlEventPublisher(event_file, max_buffer_size=5)

    for i in range(10):
        pub.publish({"event_type": "step", "index": i})

    # Buffer should retain only the last 5 events
    buffered = pub.get_buffered_events()
    assert len(buffered) == 5
    assert [e["index"] for e in buffered] == [5, 6, 7, 8, 9]

    # Replay to a listener
    replayed = []
    pub.replay(lambda evt: replayed.append(evt["index"]))
    assert replayed == [5, 6, 7, 8, 9]


def test_publisher_failure_isolation(tmp_path: Path):
    # Publisher directed to invalid read-only directory or broken writer
    broken_file = tmp_path / "non_existent_dir" / "sub" / "events.jsonl"
    pub = JsonlEventPublisher(broken_file)

    # Publishing must not raise an unhandled exception or crash the simulation
    pub.publish({"event_type": "crash_test", "val": 1})
    
    # Event should still be buffered in memory despite disk failure
    buffered = pub.get_buffered_events()
    assert len(buffered) == 1
    assert buffered[0]["event_type"] == "crash_test"


def test_composite_publisher(tmp_path: Path):
    f1 = tmp_path / "e1.jsonl"
    f2 = tmp_path / "e2.jsonl"
    p1 = JsonlEventPublisher(f1)
    p2 = JsonlEventPublisher(f2)

    composite = CompositeEventPublisher([p1, p2])
    composite.publish({"event_type": "broadcast", "data": "hello"})
    composite.flush()

    assert f1.exists()
    assert f2.exists()
    assert json.loads(f1.read_text().strip())["event_type"] == "broadcast"
    assert json.loads(f2.read_text().strip())["event_type"] == "broadcast"


def test_live_observer_non_blocking_isolation():
    observer_calls = []

    def broken_observer(event):
        observer_calls.append(event)
        raise RuntimeError("Observer plotting or GUI crashed!")

    obs = LiveObserver(broken_observer)
    # Observer notify must never raise
    obs.notify({"event_type": "metric", "temperature": 350.0})
    assert len(observer_calls) == 1
    assert observer_calls[0]["temperature"] == 350.0


def test_campaign_integration_with_event_publisher(tmp_path: Path):
    template = tmp_path / "case.template"
    template.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="pub_campaign",
        parameters={"PARAM": [10, 20]},
        templates=[str(template)],
        commands=["echo 'done'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    event_file = tmp_path / "campaign_events.jsonl"
    publisher = JsonlEventPublisher(event_file)
    observer_events = []
    publisher.add_observer(LiveObserver(lambda e: observer_events.append(e.get("event_type"))))

    campaign = Campaign(manifest, publisher=publisher)
    results = campaign.run()

    assert len(results) == 2
    publisher.flush()

    assert event_file.exists()
    lines = [json.loads(line) for line in event_file.read_text().strip().split("\n")]
    event_types = [l.get("event_type") for l in lines]
    assert "campaign_start" in event_types
    assert "campaign_complete" in event_types
    assert len(observer_events) > 0
