import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from labeeb.publisher import (
    EventPublisher,
    WebSocketEventPublisher,
    CompositeEventPublisher,
)
from labeeb.campaign import Campaign, CampaignManifest


def test_websocket_publisher_disabled_mode():
    pub = WebSocketEventPublisher("ws://localhost:9999/events", enabled=False)
    assert not pub.enabled

    # Should be complete no-op and never raise or buffer
    pub.publish({"event_type": "case_start", "case_id": 0})
    assert len(pub.get_buffered_events()) == 0


def test_websocket_publisher_offline_failure_isolation():
    # Direct to unreachable port
    pub = WebSocketEventPublisher("ws://127.0.0.1:59999/events", enabled=True, max_buffer_size=5)
    assert pub.enabled

    # Publishing must never crash or raise even when target server is down
    pub.publish({"event_type": "case_start", "case_id": 0})
    pub.publish({"event_type": "case_complete", "case_id": 0, "status": "SUCCESS"})

    # Events must remain safely buffered in memory
    buffered = pub.get_buffered_events()
    assert len(buffered) == 2
    assert buffered[0]["event_type"] == "case_start"
    assert buffered[1]["event_type"] == "case_complete"


def test_websocket_publisher_redaction():
    pub = WebSocketEventPublisher(
        "ws://127.0.0.1:59999/events",
        enabled=True,
        redact_keys=["api_token", "secret"]
    )

    pub.publish({
        "event_type": "auth",
        "api_token": "secret-xyz",
        "secret": "hidden-value",
        "public": "visible"
    })

    buffered = pub.get_buffered_events()
    assert len(buffered) == 1
    assert buffered[0]["api_token"] == "[REDACTED]"
    assert buffered[0]["secret"] == "[REDACTED]"
    assert buffered[0]["public"] == "visible"


def test_websocket_publisher_transport_mock():
    sent_payloads = []

    class MockTransport:
        def __init__(self, url):
            self.url = url
            self.connected = True

        def send(self, data):
            sent_payloads.append(data)

        def close(self):
            self.connected = False

    pub = WebSocketEventPublisher(
        "ws://mock-server/events",
        transport_factory=lambda url: MockTransport(url)
    )

    pub.publish({"event_type": "live_metric", "power": 25.0})
    pub.flush()

    assert len(sent_payloads) == 1
    decoded = json.loads(sent_payloads[0])
    assert decoded["event_type"] == "live_metric"
    assert decoded["power"] == 25.0

    pub.close()


def test_websocket_publisher_campaign_composite_integration(tmp_path: Path):
    template = tmp_path / "deck.template"
    template.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="ws_campaign",
        parameters={"PARAM": [1, 2]},
        templates=[str(template)],
        commands=["python -c 'print(\"done\")'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    ws_pub = WebSocketEventPublisher("ws://127.0.0.1:59999/events", max_buffer_size=10)
    campaign = Campaign(manifest, publisher=ws_pub)
    results = campaign.run()

    assert len(results) == 2
    # Campaign lifecycle events should be buffered in ws_pub
    buffered = ws_pub.get_buffered_events()
    assert len(buffered) >= 2
    event_types = [e.get("event_type") for e in buffered]
    assert "campaign_start" in event_types
    assert "campaign_complete" in event_types
