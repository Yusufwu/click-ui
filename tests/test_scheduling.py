from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cliui.scheduling import (
    SchedulerService,
    next_fire_times,
    validate_schedule,
)
from cliui.storage.db import init_db
from cliui.storage.repo import Store, schedule_items

TZ = ZoneInfo("Asia/Shanghai")


def schedule_payload(entry, command_path="echo", **values):
    target = next(
        node for node in entry.nodes.values() if node.path == command_path
    )
    data = {
        "_cliui_app": entry.name,
        "_cliui_command": target.node_id,
        "trigger_type": "cron",
        "cron": "0 2 * * *",
        "cron_preset": "",
        "run_at": "",
        "timezone": "Asia/Shanghai",
        "catch_up": False,
    }
    for key, value in values.items():
        data[f"c__{key}"] = value
    return data


def test_next_fire_times_are_formatted_and_sequential():
    times = next_fire_times(
        cron="0 2 * * *",
        run_at=None,
        timezone="Asia/Shanghai",
        count=3,
        after=datetime(2026, 11, 7, 12, 0, 0, tzinfo=TZ),
    )
    assert times == [
        "2026-11-08 02:00:00",
        "2026-11-09 02:00:00",
        "2026-11-10 02:00:00",
    ]


def test_validate_schedule_rejects_bad_input():
    with pytest.raises(ValueError):
        validate_schedule(
            trigger_type="cron", cron="not a cron", run_at=None, timezone="Asia/Shanghai"
        )
    with pytest.raises(ValueError):
        validate_schedule(
            trigger_type="cron", cron="0 2 * * *", run_at=None, timezone="Mars/Base"
        )
    with pytest.raises(ValueError):
        validate_schedule(
            trigger_type="once", cron=None, run_at="", timezone="Asia/Shanghai"
        )

    cron, run_at, tz = validate_schedule(
        trigger_type="once",
        cron=None,
        run_at="2026-11-08T09:30",
        timezone="Asia/Shanghai",
    )
    assert cron is None
    assert run_at == "2026-11-08 09:30:00"
    assert tz == "Asia/Shanghai"


def test_schedule_claim_is_atomic(tmp_path):
    db_path = tmp_path / "claim.sqlite3"
    first = Store(db_path)
    second = Store(db_path)
    schedule_id = first.create_schedule(
        app_name="app",
        command_path="echo",
        argv=["echo", "x"],
        params={},
        argv_label="app echo x",
        cron="0 2 * * *",
        run_at=None,
        timezone="Asia/Shanghai",
        catch_up=False,
        enabled=True,
        created_by=1,
        created_by_name="admin",
        next_run_at="2026-11-08 02:00:00",
    )

    assert first.claim_schedule_run(
        schedule_id,
        expected_next_run_at="2026-11-08 02:00:00",
        next_run_at="2026-11-09 02:00:00",
        now="2026-11-08 02:00:01",
    )
    assert not second.claim_schedule_run(
        schedule_id,
        expected_next_run_at="2026-11-08 02:00:00",
        next_run_at="2026-11-09 02:00:00",
        now="2026-11-08 02:00:02",
    )
    assert not first.claim_schedule_run(
        schedule_id,
        expected_next_run_at="2020-01-01 00:00:00",
        next_run_at="2026-11-10 02:00:00",
        now="2026-11-08 02:00:03",
    )


def test_create_list_toggle_and_delete_schedule(admin_client, fixture_entry, store):
    data = schedule_payload(fixture_entry, text="hi")
    response = admin_client.post("/api/schedules", json=data)
    body = response.get_json()
    assert body["status"] == 0, body
    schedule_id = body["data"]["schedule_id"]
    assert body["data"]["next_run_at"].endswith("02:00:00")

    listed = admin_client.get("/api/schedules").get_json()
    assert listed["data"]["total"] == 1
    item = listed["data"]["items"][0]
    assert item["command_path"] == "echo"
    assert item["cron"] == "0 2 * * *"
    assert item["enabled"] == 1
    assert "argv_json" not in item

    response = admin_client.post(f"/api/schedules/{schedule_id}/toggle?enabled=0")
    assert response.get_json()["status"] == 0
    assert store.get_schedule(schedule_id)["enabled"] == 0

    response = admin_client.post(f"/api/schedules/{schedule_id}/toggle?enabled=1")
    assert response.get_json()["data"]["next_run_at"]

    response = admin_client.delete(f"/api/schedules/{schedule_id}")
    assert response.get_json()["status"] == 0
    assert store.get_schedule(schedule_id) is None


def test_schedule_params_are_validated(admin_client, fixture_entry):
    data = schedule_payload(fixture_entry, command_path="needs", text="x")
    body = admin_client.post("/api/schedules", json=data).get_json()
    assert body["status"] == 422
    assert "c__token" in body["errors"]


def test_schedule_preview(admin_client, fixture_entry):
    data = schedule_payload(fixture_entry, text="hi")
    body = admin_client.post("/api/schedules/preview", json=data).get_json()
    assert body["status"] == 0
    assert len(body["data"]["times"]) == 3
    assert "未来触发时间" in body["msg"]

    data["cron"] = ""
    data["trigger_type"] = "once"
    data["run_at"] = "2020-01-01 00:00:00"
    body = admin_client.post("/api/schedules/preview", json=data).get_json()
    assert body["data"]["times"] == []


def test_run_now_records_schedule_trigger(admin_client, fixture_entry, store):
    data = schedule_payload(fixture_entry, text="run-now")
    schedule_id = admin_client.post("/api/schedules", json=data).get_json()["data"][
        "schedule_id"
    ]
    body = admin_client.post(f"/api/schedules/{schedule_id}/run").get_json()
    assert body["status"] == 0
    execution_id = body["data"]["execution_id"]

    record = store.get_execution(execution_id)
    assert record["trigger"] == "schedule"
    assert record["schedule_id"] == schedule_id
    assert record["status"] == "success"
    assert "run-now" in record["stdout"]

    schedule = store.get_schedule(schedule_id)
    assert schedule["last_status"] == "success"
    assert schedule["last_execution_id"] == execution_id


def test_schedule_is_owned_per_user(web_app, store, admin_client, fixture_entry):
    data = schedule_payload(fixture_entry, text="alice")
    schedule_id = admin_client.post("/api/schedules", json=data).get_json()["data"][
        "schedule_id"
    ]

    store.create_user("alice", "alicepass")
    client = web_app.test_client()
    client.post("/login", data={"username": "alice", "password": "alicepass"})
    assert client.get("/api/schedules").get_json()["data"]["total"] == 0
    assert client.post(f"/api/schedules/{schedule_id}/run").status_code == 403

    # The admin sees every schedule, including other users' entries.
    assert admin_client.get("/api/schedules").get_json()["data"]["total"] == 1

    # Alice's own schedule is visible to her.
    alice_data = schedule_payload(fixture_entry, text="mine")
    alice_id = client.post("/api/schedules", json=alice_data).get_json()["data"][
        "schedule_id"
    ]
    assert client.get("/api/schedules").get_json()["data"]["total"] == 1
    assert client.post(f"/api/schedules/{alice_id}/run").get_json()["status"] == 0


def test_recover_missed_marks_missed(fixture_entry, store):
    schedule_id = store.create_schedule(
        app_name=fixture_entry.name,
        command_path="echo",
        argv=["echo", "missed"],
        params={},
        argv_label="app echo missed",
        cron="0 2 * * *",
        run_at=None,
        timezone="Asia/Shanghai",
        catch_up=False,
        enabled=True,
        created_by=1,
        created_by_name="admin",
        next_run_at="2020-01-01 02:00:00",
    )
    service = SchedulerService(store=store, apps_by_name={fixture_entry.name: fixture_entry})
    service.recover_missed()

    row = store.get_schedule(schedule_id)
    assert row["last_status"] == "missed"
    assert row["last_run_at"] is None
    assert row["next_run_at"] > "2020-01-01 02:00:00"

    executions, _total = store.list_executions(user_id=None)
    assert executions == []


def test_recover_missed_catch_up_runs_once(fixture_entry, store):
    schedule_id = store.create_schedule(
        app_name=fixture_entry.name,
        command_path="echo",
        argv=["echo", "caught-up"],
        params={},
        argv_label="app echo caught-up",
        cron="0 2 * * *",
        run_at=None,
        timezone="Asia/Shanghai",
        catch_up=True,
        enabled=True,
        created_by=1,
        created_by_name="admin",
        next_run_at="2020-01-01 02:00:00",
    )
    service = SchedulerService(store=store, apps_by_name={fixture_entry.name: fixture_entry})
    service.recover_missed()

    row = store.get_schedule(schedule_id)
    assert row["last_status"] == "success"
    assert row["last_execution_id"]
    assert row["next_run_at"] != "2020-01-01 02:00:00"

    executions, _total = store.list_executions(user_id=None)
    assert len(executions) == 1
    assert executions[0]["trigger"] == "schedule"
    assert executions[0]["schedule_id"] == schedule_id
    assert "caught-up" in executions[0]["stdout"]


def test_sync_loads_enabled_jobs(fixture_entry, store):
    store.create_schedule(
        app_name=fixture_entry.name,
        command_path="echo",
        argv=["echo", "x"],
        params={},
        argv_label="app echo x",
        cron="0 2 * * *",
        run_at=None,
        timezone="Asia/Shanghai",
        catch_up=False,
        enabled=True,
        created_by=1,
        created_by_name="admin",
        next_run_at=(datetime.now(TZ) + timedelta(hours=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )
    store.create_schedule(
        app_name=fixture_entry.name,
        command_path="echo",
        argv=["echo", "y"],
        params={},
        argv_label="app echo y",
        cron="0 2 * * *",
        run_at=None,
        timezone="Asia/Shanghai",
        catch_up=False,
        enabled=False,
        created_by=1,
        created_by_name="admin",
        next_run_at=None,
    )
    service = SchedulerService(store=store, apps_by_name={fixture_entry.name: fixture_entry})
    service.sync()
    assert len(service.scheduler.get_jobs()) == 1


def test_migration_adds_schedule_columns(tmp_path):
    legacy = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(legacy))
    conn.execute(
        """
        CREATE TABLE executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            app TEXT NOT NULL,
            command_id TEXT NOT NULL,
            command_path TEXT NOT NULL,
            params_json TEXT NOT NULL,
            argv_json TEXT NOT NULL,
            argv_label TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            exit_code INTEGER,
            stdout TEXT,
            stderr TEXT,
            exception TEXT,
            duration_ms INTEGER,
            batch_id INTEGER,
            batch_index INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    init_db(legacy)
    conn = sqlite3.connect(str(legacy))
    columns = {row[1] for row in conn.execute("PRAGMA table_info(executions)")}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()

    assert {"trigger", "schedule_id"} <= columns
    assert {"schedules", "app_specs"} <= tables


def test_multi_item_plan_runs_each_command(admin_client, fixture_entry, store):
    data = schedule_payload(fixture_entry, text="first")
    schedule_id = admin_client.post("/api/schedules", json=data).get_json()["data"][
        "schedule_id"
    ]

    second = schedule_payload(fixture_entry, text="second")
    body = admin_client.post(
        f"/api/schedules/{schedule_id}/items", json=second
    ).get_json()
    assert body["status"] == 0, body
    assert body["data"]["items_count"] == 2

    item = admin_client.get("/api/schedules").get_json()["data"]["items"][0]
    assert item["items_count"] == 2
    assert "共 2 条" in item["command_summary"]

    body = admin_client.post(f"/api/schedules/{schedule_id}/run").get_json()
    assert body["status"] == 0, body
    rows = store.schedule_executions(schedule_id)
    assert len(rows) == 2
    assert all(row["trigger"] == "schedule" for row in rows)
    assert "first" in rows[1]["stdout"]
    assert "second" in rows[0]["stdout"]

    schedule = store.get_schedule(schedule_id)
    assert schedule["last_status"] == "success"
    assert schedule["last_execution_id"] == rows[0]["id"]


def test_schedule_edit_and_duplicate(admin_client, fixture_entry, store):
    data = schedule_payload(fixture_entry, text="edit")
    schedule_id = admin_client.post("/api/schedules", json=data).get_json()["data"][
        "schedule_id"
    ]

    body = admin_client.post(
        f"/api/schedules/{schedule_id}/edit",
        json={
            "trigger_type": "cron",
            "cron": "0 3 * * *",
            "timezone": "Asia/Shanghai",
        },
    ).get_json()
    assert body["status"] == 0, body
    assert body["data"]["next_run_at"].endswith("03:00:00")
    assert store.get_schedule(schedule_id)["cron"] == "0 3 * * *"

    invalid = admin_client.post(
        f"/api/schedules/{schedule_id}/edit",
        json={"trigger_type": "cron", "cron": "not a cron", "timezone": "Asia/Shanghai"},
    ).get_json()
    assert invalid["status"] == 1
    assert store.get_schedule(schedule_id)["cron"] == "0 3 * * *"

    duplicated = admin_client.post(
        f"/api/schedules/{schedule_id}/duplicate"
    ).get_json()
    assert duplicated["status"] == 0, duplicated
    new_id = duplicated["data"]["schedule_id"]
    assert new_id != schedule_id
    assert admin_client.get("/api/schedules").get_json()["data"]["total"] == 2
    assert store.get_schedule(new_id)["cron"] == "0 3 * * *"
    assert schedule_items(store.get_schedule(new_id)) == schedule_items(
        store.get_schedule(schedule_id)
    )


def test_schedule_detail_page_and_item_removal(admin_client, fixture_entry, store):
    data = schedule_payload(fixture_entry, text="detail")
    schedule_id = admin_client.post("/api/schedules", json=data).get_json()["data"][
        "schedule_id"
    ]
    admin_client.post(
        f"/api/schedules/{schedule_id}/items",
        json=schedule_payload(fixture_entry, text="second"),
    )

    response = admin_client.get(f"/schedules/{schedule_id}")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "计划设置" in page
    assert "命令列表（2 条）" in page
    assert f"/schedules/{schedule_id}/items/0/remove" in page

    response = admin_client.post(f"/schedules/{schedule_id}/items/0/remove")
    assert response.status_code == 302
    assert len(schedule_items(store.get_schedule(schedule_id))) == 1

    response = admin_client.post(f"/schedules/{schedule_id}/items/0/remove")
    assert response.status_code == 400


def test_schedule_page_forms_run_toggle_and_copy(admin_client, fixture_entry, store):
    data = schedule_payload(fixture_entry, text="forms")
    schedule_id = admin_client.post("/api/schedules", json=data).get_json()["data"][
        "schedule_id"
    ]

    response = admin_client.post(f"/schedules/{schedule_id}/run")
    assert response.status_code == 302
    assert store.get_schedule(schedule_id)["last_status"] == "success"

    response = admin_client.post(
        f"/schedules/{schedule_id}/toggle", data={"enabled": "0"}
    )
    assert response.status_code == 302
    assert store.get_schedule(schedule_id)["enabled"] == 0

    response = admin_client.post(f"/schedules/{schedule_id}/duplicate")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/schedules/")
    assert admin_client.get("/api/schedules").get_json()["data"]["total"] == 2
