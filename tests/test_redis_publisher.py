import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from labeeb.publisher import RedisStreamEventPublisher
from labeeb.campaign import Campaign, CampaignManifest


def test_redis_publisher_disabled_mode():
    pub = RedisStreamEventPublisher(stream_key="labeeb:events", url="redis://localhost:6379/0", enabled=False)
    assert not pub.enabled

    pub.publish({"event_type": "test_event", "val": 123})
    assert len(pub.get_buffered_events()) == 0


def test_redis_publisher_offline_failure_isolation():
    # Point to unreachable redis host
    pub = RedisStreamEventPublisher(
        stream_key="sim:events",
        url="redis://127.0.0.1:59998/0",
        enabled=True,
        max_buffer_size=5
    )
    assert pub.enabled

    # Publishing must not raise an unhandled exception or crash the simulation
    pub.publish({"event_type": "case_start", "case_id": 0})
    pub.publish({"event_type": "case_complete", "case_id": 0, "status": "SUCCESS"})

    # Events must remain safely buffered in memory
    buffered = pub.get_buffered_events()
    assert len(buffered) == 2
    assert buffered[0]["event_type"] == "case_start"
    assert buffered[1]["event_type"] == "case_complete"


def test_redis_publisher_redaction():
    pub = RedisStreamEventPublisher(
        stream_key="sim:events",
        url="redis://127.0.0.1:59998/0",
        enabled=True,
        redact_keys=["auth_token", "secret"]
    )

    pub.publish({
        "event_type": "auth",
        "auth_token": "secret-12345",
        "secret": "confidential",
        "public_data": "accessible"
    })

    buffered = pub.get_buffered_events()
    assert len(buffered) == 1
    assert buffered[0]["auth_token"] == "[REDACTED]"
    assert buffered[0]["secret"] == "[REDACTED]"
    assert buffered[0]["public_data"] == "accessible"


def test_redis_publisher_xadd_mock():
    xadd_calls = []

    class MockRedisClient:
        def xadd(self, stream_key, fields, maxlen=None, approximate=True):
            xadd_calls.append({"stream_key": stream_key, "fields": fields, "maxlen": maxlen})
            return "1600000000000-0"

        def close(self):
            pass

    pub = RedisStreamEventPublisher(
        stream_key="core:metrics",
        client_factory=lambda url: MockRedisClient(),
        maxlen=5000
    )

    pub.publish({"event_type": "metric", "temperature": 325.5})
    pub.flush()

    assert len(xadd_calls) == 1
    assert xadd_calls[0]["stream_key"] == "core:metrics"
    assert xadd_calls[0]["maxlen"] == 5000
    payload_json = json.loads(xadd_calls[0]["fields"]["payload"])
    assert payload_json["temperature"] == 325.5

    pub.close()


def test_redis_publisher_campaign_integration(tmp_path: Path):
    template = tmp_path / "deck.template"
    template.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="redis_campaign",
        parameters={"PARAM": [5, 10]},
        templates=[str(template)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    redis_pub = RedisStreamEventPublisher(
        stream_key="campaign:events",
        url="redis://127.0.0.1:59998/0",
        max_buffer_size=10
    )
    campaign = Campaign(manifest, publisher=redis_pub)
    results = campaign.run()

    assert len(results) == 2
    buffered = redis_pub.get_buffered_events()
    assert len(buffered) >= 2
    event_types = [e.get("event_type") for e in buffered]
    assert "campaign_start" in event_types
    assert "campaign_complete" in event_types
