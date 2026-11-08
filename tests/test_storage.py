from __future__ import annotations

from cliui.storage.repo import Store, summarize_params


def test_users_and_password_hashing(store):
    assert store.count_users() == 1
    assert store.create_user("alice", "secret1") is True
    assert store.create_user("alice", "secret1") is False
    import pytest

    with pytest.raises(ValueError):
        store.create_user("bob", "123")  # too short
    assert store.get_user_by_name("alice")["username"] == "alice"

    alice = store.authenticate("alice", "secret1")
    assert alice is not None
    assert alice["last_login_at"]
    assert store.authenticate("alice", "wrong") is None
    assert store.authenticate("missing", "secret1") is None


def test_execution_isolation_and_filters(store):
    store.create_user("alice", "secret1")
    admin = store.get_user_by_name("admin")
    alice = store.get_user_by_name("alice")

    first = store.record_execution(
        user_id=admin["id"],
        username="admin",
        app="demo",
        command_id="n1",
        command_path="echo",
        params={"c__text": "one"},
        argv=["echo", "one"],
        argv_label="demo echo one",
        status="success",
        exit_code=0,
        stdout="one",
        stderr="",
        exception="",
        duration_ms=10,
    )
    second = store.record_execution(
        user_id=alice["id"],
        username="alice",
        app="demo",
        command_id="n2",
        command_path="sub run",
        params={"c__value": "two"},
        argv=["sub", "run", "two"],
        argv_label="demo sub run two",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="err",
        exception="boom",
        duration_ms=20,
    )

    admin_rows, admin_total = store.list_executions(user_id=admin["id"])
    assert admin_total == 1
    assert admin_rows[0]["id"] == first

    alice_rows, alice_total = store.list_executions(user_id=alice["id"])
    assert alice_total == 1
    assert alice_rows[0]["id"] == second

    rows, total = store.list_executions(user_id=None, command="run")
    assert total == 1
    assert rows[0]["id"] == second

    rows, total = store.list_executions(user_id=None, status="success", app="demo")
    assert total == 1
    assert rows[0]["id"] == first

    rows, total = store.list_executions(user_id=None, username="alice")
    assert total == 1

    record = store.get_execution(second)
    assert record["stdout"] == ""
    assert record["exception"] == "boom"


def test_queue_order_and_moves(store):
    store.create_user("alice", "secret1")
    alice = store.get_user_by_name("alice")

    ids = []
    for index in range(3):
        ids.append(
            store.add_queue_item(
                user_id=alice["id"],
                username="alice",
                app="demo",
                command_id=f"n{index}",
                command_path=f"cmd{index}",
                params={},
                argv=["cmd"],
                params_label="",
                argv_label=f"demo cmd{index}",
            )
        )

    assert store.queue_count(alice["id"]) == 3
    items = store.queue_items(alice["id"])
    assert [item["id"] for item in items] == ids

    assert store.move_queue_item(ids[2], alice["id"], "up") is True
    items = store.queue_items(alice["id"])
    assert [item["id"] for item in items] == [ids[0], ids[2], ids[1]]

    assert store.delete_queue_item(ids[0], alice["id"]) is True
    assert store.delete_queue_item(ids[0], alice["id"]) is False
    assert store.queue_count(alice["id"]) == 2

    assert store.clear_queue(alice["id"]) == 2
    assert store.queue_count(alice["id"]) == 0
    assert store.list_queue(user_id=alice["id"])[1] == 0


def test_batches(store):
    store.create_user("alice", "secret1")
    alice = store.get_user_by_name("alice")
    batch = store.create_batch(
        user_id=alice["id"],
        username="alice",
        app="demo",
        status="running",
        title="test batch",
    )
    store.update_batch(batch, status="success", total=2, succeeded=2, failed=0)
    row = store.get_batch(batch)
    assert row["status"] == "success"
    assert row["total"] == 2
    assert row["succeeded"] == 2
    assert row["finished_at"]

    rows, total = store.list_batches(user_id=alice["id"])
    assert total == 1
    assert rows[0]["id"] == batch


def test_summarize_params_hides_long_values():
    summary = summarize_params(
        {"c__text": "x" * 200, "c__flag": True, "c__empty": "", "c__list": [1, 2]}
    )
    assert summary
    assert len(summary) < 200
    assert "flag" in summary
    assert "list" in summary


def test_large_output_is_compressed_and_decoded(store):
    import sqlite3

    big = "line of output\n" * 4000
    record_id = store.record_execution(
        user_id=1,
        username="admin",
        app="demo",
        command_id="n1",
        command_path="echo",
        params={},
        argv=["echo"],
        argv_label="demo echo",
        status="success",
        exit_code=0,
        stdout=big,
        stderr="",
        exception="",
        duration_ms=100,
    )
    conn = sqlite3.connect(str(store.db_path))
    raw = conn.execute(
        "SELECT stdout FROM executions WHERE id = ?", (record_id,)
    ).fetchone()[0]
    conn.close()
    assert raw.startswith("cliui-gzip:")
    assert store.get_execution(record_id)["stdout"] == big
    rows, _total = store.list_executions(user_id=None)
    assert rows[0]["stdout"] == big


def test_purge_executions_respects_retention(store):
    import sqlite3

    keep = store.record_execution(
        user_id=1,
        username="admin",
        app="demo",
        command_id="n1",
        command_path="echo",
        params={},
        argv=["echo"],
        argv_label="demo echo",
        status="success",
        exit_code=0,
        stdout="fresh",
        stderr="",
        exception="",
        duration_ms=0,
    )
    old = store.record_execution(
        user_id=1,
        username="admin",
        app="demo",
        command_id="n2",
        command_path="echo",
        params={},
        argv=["echo"],
        argv_label="demo echo",
        status="success",
        exit_code=0,
        stdout="old",
        stderr="",
        exception="",
        duration_ms=0,
    )
    conn = sqlite3.connect(str(store.db_path))
    conn.execute(
        "UPDATE executions SET created_at = '2000-01-01 00:00:00' WHERE id = ?",
        (old,),
    )
    conn.commit()
    conn.close()

    assert store.purge_executions(retention_days=0) == 0
    assert store.purge_executions(retention_days=30) == 1
    assert store.get_execution(old) is None
    assert store.get_execution(keep) is not None
