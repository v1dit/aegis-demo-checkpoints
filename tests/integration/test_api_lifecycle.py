import time

from fastapi.testclient import TestClient

from backend.app.main import app


def test_train_eval_replay_lifecycle(tmp_path) -> None:
    client = TestClient(app)

    train_resp = client.post(
        "/train/run",
        json={
            "run_name": "blue_train_main",
            "seed": 42,
            "gpu_ids": [5, 6, 7],
            "max_timesteps": 2000,
            "config_profile": "weekend_v1",
        },
    )
    assert train_resp.status_code == 200
    run_id = train_resp.json()["run_id"]

    status = None
    for _ in range(60):
        status_resp = client.get(f"/train/status/{run_id}")
        assert status_resp.status_code == 200
        status = status_resp.json()
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert status is not None
    assert status["status"] == "completed"

    checkpoint_id = "checkpoint_blue_demo_best"
    if status["checkpoint_path"]:
        checkpoint_id = status["checkpoint_path"].split("/")[-1].replace(".json", "")

    eval_resp = client.post(
        "/eval/run",
        json={
            "checkpoint_id": checkpoint_id,
            "suite_id": "heldout_suite_v1",
            "seeds": [1001, 1002, 1003, 1004],
        },
    )
    assert eval_resp.status_code == 200
    eval_id = eval_resp.json()["eval_id"]

    report = None
    for _ in range(120):
        report_resp = client.get(f"/eval/report/{eval_id}")
        if report_resp.status_code == 200:
            report = report_resp.json()
            break
        assert report_resp.status_code == 409
        time.sleep(0.05)

    assert report is not None
    assert "kpis" in report
    assert "damage_reduction_vs_no_defense" in report["kpis"]

    replay_list = client.get("/replay/list")
    assert replay_list.status_code == 200
