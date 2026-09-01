import pytest
import pandas as pd
from labeeb.shared_memory import (
    CampaignMemory,
    InMemorySharedBackend,
    SharedMemoryError,
)
from labeeb.campaign import Campaign, CampaignManifest


def test_in_memory_shared_backend_crud():
    backend = InMemorySharedBackend()
    backend.set("alpha", 42)
    assert backend.get("alpha") == 42
    assert backend.get("missing", default="none") == "none"

    backend.update({"beta": 100, "gamma": "test"})
    assert set(backend.keys()) == {"alpha", "beta", "gamma"}

    snap = backend.snapshot()
    assert snap == {"alpha": 42, "beta": 100, "gamma": "test"}

    # Modifying snapshot does not mutate backend storage
    snap["alpha"] = 999
    assert backend.get("alpha") == 42

    backend.clear()
    assert backend.keys() == []


def test_in_memory_shared_backend_subscribers():
    backend = InMemorySharedBackend()
    events = []

    def on_change(k, v):
        events.append((k, v))

    backend.subscribe(on_change)
    backend.set("x", 1.23)
    backend.update({"y": 2.34})

    assert ("x", 1.23) in events
    assert ("y", 2.34) in events


def test_campaign_memory_recording_and_retrieval():
    memory = CampaignMemory()
    memory.record_case(0, {"RHO": 19.25, "TEMP": 300.0, "status": "SUCCESS"})
    memory.record_case(1, {"RHO": 19.30, "TEMP": 310.0, "status": "SUCCESS"})

    assert memory.get_case(0) == {"RHO": 19.25, "TEMP": 300.0, "status": "SUCCESS"}
    assert memory.get_case(1) == {"RHO": 19.30, "TEMP": 310.0, "status": "SUCCESS"}
    assert memory.get_case(2) is None

    # Series extraction
    rho_series = memory.get_series("RHO")
    assert rho_series == [19.25, 19.30]


def test_campaign_memory_validation():
    memory = CampaignMemory()
    with pytest.raises(SharedMemoryError, match="non-negative integer"):
        memory.record_case(-1, {"a": 1})

    with pytest.raises(SharedMemoryError, match="dictionary"):
        memory.record_case(0, "not_a_dict")  # type: ignore


def test_campaign_memory_dataframe_and_online_summary():
    memory = CampaignMemory()
    memory.record_case(0, {"T": 100.0, "P": 1.0, "tag": "A"})
    memory.record_case(1, {"T": 200.0, "P": 2.0, "tag": "B"})
    memory.record_case(2, {"T": 300.0, "P": 3.0, "tag": "C"})

    df = memory.to_dataframe()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    assert list(df["T"]) == [100.0, 200.0, 300.0]

    summary = memory.online_summary(metrics=["T", "P"])
    assert summary["T"]["count"] == 3.0
    assert summary["T"]["mean"] == 200.0
    assert summary["T"]["min"] == 100.0
    assert summary["T"]["max"] == 300.0
    assert summary["P"]["mean"] == 2.0


def test_campaign_memory_listeners():
    memory = CampaignMemory()
    received = []

    memory.add_listener(lambda case_id, data: received.append((case_id, data.get("val"))))
    memory.record_case(0, {"val": 10})
    memory.record_case(1, {"val": 20})

    assert received == [(0, 10), (1, 20)]


def test_campaign_integration_with_memory(tmp_path):
    template = tmp_path / "case.template"
    template.write_text("PARAM = #PARAM#\n")

    manifest = CampaignManifest(
        name="mem_test",
        parameters={"PARAM": [1, 2, 3]},
        templates=[str(template)],
        commands=["echo 'done'"],
        execution={"main_dir": str(tmp_path), "run_dir": "runs"}
    )

    custom_memory = CampaignMemory()
    campaign = Campaign(manifest, memory=custom_memory)
    assert campaign.memory is custom_memory

    results = campaign.run()
    assert len(results) == 3

    # Verify memory recorded all cases online
    all_cases = custom_memory.get_all_cases()
    assert len(all_cases) == 3
    assert all_cases[0]["PARAM"] == 1
    assert all_cases[0]["status"] == "SUCCESS"
    assert all_cases[1]["PARAM"] == 2
    assert all_cases[2]["PARAM"] == 3


def test_record_case_post_mutation_isolation():
    memory = CampaignMemory()
    caller_dict = {"nested": {"count": 1}, "values": [1, 2, 3]}
    memory.record_case(0, caller_dict)

    # Mutate caller dict post-record
    caller_dict["nested"]["count"] = 999
    caller_dict["values"].append(4)

    # Stored state in memory and backend must remain unaffected
    stored = memory.get_case(0)
    assert stored["nested"]["count"] == 1
    assert stored["values"] == [1, 2, 3]

    backend_stored = memory.backend.get("case_0")
    assert backend_stored["nested"]["count"] == 1
    assert backend_stored["values"] == [1, 2, 3]
