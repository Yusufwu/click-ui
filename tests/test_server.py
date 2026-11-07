from __future__ import annotations

import io
import json
import re
from pathlib import Path

from cliui.registry import load_app_entry, reload_app_entry
from cliui.web.server import create_app


def node(entry, path):
    for item in entry.nodes.values():
        if item.path == path:
            return item
    raise AssertionError(path)


def page_json(html: str) -> dict:
    match = re.search(
        r'<script id="cliui-page" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    assert match, "page JSON not found"
    return json.loads(match.group(1))


def payload(entry, command_path, **values):
    target = node(entry, command_path)
    data = {
        "_cliui_app": entry.name,
        "_cliui_command": target.node_id,
    }
    for key, value in values.items():
        data[f"c__{key}"] = value
    return data, target


def test_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    response = client.post("/api/preview", json={})
    assert response.status_code == 401
    assert response.get_json()["status"] == 1


def test_login_failure_and_success(client):
    response = client.post(
        "/login", data={"username": "admin", "password": "wrong"}
    )
    assert response.status_code == 200
    assert "用户名或密码不正确" in response.get_data(as_text=True)

    response = client.post(
        "/login", data={"username": "admin", "password": "adminpass"}
    )
    assert response.status_code == 302


def test_index_renders_amis_page(admin_client, fixture_entry):
    echo = node(fixture_entry, "echo")
    response = admin_client.get(f"/?app=fixture&cmd={echo.node_id}")
    assert response.status_code == 200
    page = page_json(response.get_data(as_text=True))
    assert page["type"] == "page"
    body_text = json.dumps(page, ensure_ascii=False)
    assert "echo" in body_text
    assert "执行结果" in body_text
    assert "加入队列" in body_text


def _walk(schema):
    if isinstance(schema, dict):
        yield schema
        for value in schema.values():
            yield from _walk(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _walk(value)


def test_command_form_has_actions_and_file_fields(admin_client, fixture_entry):
    readfile = node(fixture_entry, "readfile")
    response = admin_client.get(f"/?app=fixture&cmd={readfile.node_id}")
    page = page_json(response.get_data(as_text=True))

    forms = [item for item in _walk(page) if item.get("type") == "form"]
    assert forms, "form schema missing"
    form = forms[0]
    assert form.get("wrapWithPanel") is not False
    actions = {action.get("label"): action for action in form.get("actions", [])}
    assert "执行" in actions
    assert "加入队列" in actions
    assert actions["执行"]["tooltip"] == "立即执行命令，显示结果"
    assert "记录队列" in actions["加入队列"]["tooltip"]
    page_text = json.dumps(page, ensure_ascii=False)
    assert "记录模式" not in page_text
    assert "_cliui_record_mode" not in page_text

    file_fields = [item for item in _walk(page) if item.get("type") == "input-file"]
    assert file_fields, "file field missing"
    for field in file_fields:
        assert "accept" not in field, "accept must be omitted so any file passes AMIS validation"


def test_choice_fields_render_as_radio_and_checkbox_groups(admin_client, fixture_entry):
    run = node(fixture_entry, "sub run")
    response = admin_client.get(f"/?app=fixture&cmd={run.node_id}")
    page = page_json(response.get_data(as_text=True))
    fields = {
        item.get("name"): item
        for item in _walk(page)
        if item.get("name") in ("c__mode", "c__color")
    }

    mode = fields["c__mode"]
    assert mode["type"] == "radios"
    assert [option["value"] for option in mode["options"]] == ["a", "b"]

    color = fields["c__color"]
    assert color["type"] == "checkboxes"
    assert color["joinValues"] is False
    assert color["extractValue"] is True
    assert [option["value"] for option in color["options"]] == ["red", "green", "blue"]


def test_password_and_uuid_fields_use_human_friendly_inputs(admin_client, fixture_entry):
    password_node = node(fixture_entry, "password")
    page = page_json(
        admin_client.get(f"/?app=fixture&cmd={password_node.node_id}").get_data(as_text=True)
    )
    fields = {
        item.get("name"): item for item in _walk(page) if isinstance(item.get("name"), str)
    }
    pwd = fields["c__value"]
    assert pwd["type"] == "input-password"
    assert pwd["label"] == "Value"
    assert "掩码" in pwd["description"]

    data, _ = payload(fixture_entry, "password", value="secret-value")
    body = admin_client.post("/api/execute", json=data).get_json()
    assert body["status"] == 0
    assert "len=12" in body["data"]["result_stdout"]

    uuid_node = node(fixture_entry, "uuid")
    page = page_json(
        admin_client.get(f"/?app=fixture&cmd={uuid_node.node_id}").get_data(as_text=True)
    )
    fields = {
        item.get("name"): item for item in _walk(page) if isinstance(item.get("name"), str)
    }
    uuid_field = fields["c__value"]
    assert uuid_field["label"] == "Value"
    assert uuid_field["validations"]["matchRegexp"].startswith("^")
    assert "UUID" in uuid_field["validationErrors"]["matchRegexp"]

    data, _ = payload(fixture_entry, "uuid", value="0f8fad5b-d9cb-469f-a165-70867728950e")
    body = admin_client.post("/api/execute", json=data).get_json()
    assert body["status"] == 0
    assert "0f8fad5b-d9cb-469f-a165-70867728950e" in body["data"]["result_stdout"]


def test_missing_page_is_rendered_for_anonymous_visitors(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "页面不存在" in response.get_data(as_text=True)


def test_overview_and_pages_render(admin_client, fixture_entry):
    for path in ("/", "/records", "/queue", "/batches"):
        response = admin_client.get(path)
        assert response.status_code == 200
        assert "cliui-page" in response.get_data(as_text=True)


def test_preview_and_execute(admin_client, fixture_entry, store):
    data, echo = payload(fixture_entry, "echo", text="hi")

    response = admin_client.post("/api/preview", json=data)
    body = response.get_json()
    assert body["status"] == 0
    assert body["data"]["result_status"] == "preview"
    assert "--root-name=root" in body["data"]["result_argv"]
    assert body["data"]["result_record_id"] is None

    response = admin_client.post("/api/execute", json=data)
    body = response.get_json()
    assert body["status"] == 0
    result = body["data"]
    assert result["result_status"] == "success"
    assert "leaf:hi\n" in result["result_stdout"]
    assert result["result_stderr"] == ""
    assert isinstance(result["result_record_id"], int)

    record = store.get_execution(result["result_record_id"])
    assert record["username"] == "admin"
    assert record["command_path"] == "echo"
    assert json.loads(record["params_json"])["c__text"] == "hi"


def test_server_side_validation(admin_client, fixture_entry):
    data, needs = payload(fixture_entry, "needs")
    response = admin_client.post("/api/execute", json=data)
    body = response.get_json()
    assert body["status"] == 422
    assert "c__token" in body["errors"]


def test_execution_failure_is_still_a_completed_request(admin_client, fixture_entry):
    data, boom = payload(fixture_entry, "boom")
    response = admin_client.post("/api/execute", json=data)
    body = response.get_json()
    assert body["status"] == 0
    assert body["data"]["result_status"] == "failed"
    assert "RuntimeError" in body["data"]["result_exception"]


def test_records_are_isolated_per_user(web_app, store, fixture_entry, admin_client):
    data, _echo = payload(fixture_entry, "echo", text="admin")
    admin_client.post("/api/execute", json=data)

    store.create_user("alice", "secret1")
    alice_client = web_app.test_client()
    alice_client.post("/login", data={"username": "alice", "password": "secret1"})
    data, _echo = payload(fixture_entry, "echo", text="alice")
    response = alice_client.post("/api/execute", json=data)
    assert response.get_json()["status"] == 0

    response = alice_client.get("/api/records")
    body = response.get_json()
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["username"] == "alice"

    response = admin_client.get("/api/records")
    assert response.get_json()["data"]["total"] == 2

    admin_record = admin_client.get("/api/records").get_json()["data"]["items"][-1]
    response = alice_client.get(f"/records/{admin_record['id']}")
    assert response.status_code == 403


def test_record_detail_and_rerun_preload(admin_client, fixture_entry, store):
    data, echo = payload(fixture_entry, "echo", text="remember me")
    response = admin_client.post("/api/execute", json=data)
    record_id = response.get_json()["data"]["result_record_id"]

    response = admin_client.get(f"/records/{record_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "remember me" in html
    assert page_json(html)["type"] == "page"

    response = admin_client.get(
        f"/?app=fixture&cmd={echo.node_id}&record={record_id}"
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "remember me" in html
    assert "c__text" in html


def test_queue_crud_and_batch_run(admin_client, fixture_entry, store):
    first, echo = payload(fixture_entry, "echo", text="one")
    response = admin_client.post("/api/queue", json=first)
    body = response.get_json()
    assert body["status"] == 0
    assert body["data"]["queue_count"] == 1
    first_id = body["data"]["queue_item_id"]

    second, _echo = payload(fixture_entry, "echo", text="two")
    response = admin_client.post("/api/queue", json=second)
    second_id = response.get_json()["data"]["queue_item_id"]

    response = admin_client.get("/api/queue")
    body = response.get_json()
    assert body["data"]["total"] == 2
    ids = [item["id"] for item in body["data"]["items"]]
    assert ids == [first_id, second_id]

    response = admin_client.post(f"/api/queue/{second_id}/move?direction=up")
    assert response.get_json()["status"] == 0
    ids = [
        item["id"]
        for item in admin_client.get("/api/queue").get_json()["data"]["items"]
    ]
    assert ids == [second_id, first_id]

    response = admin_client.post("/api/batch/run")
    body = response.get_json()
    assert body["status"] == 0
    batch_id = body["data"]["batch_id"]
    assert body["data"]["total"] == 2
    assert body["data"]["succeeded"] == 2
    assert body["data"]["failed"] == 0
    assert admin_client.get("/api/queue").get_json()["data"]["total"] == 0

    items = store.batch_executions(batch_id)
    assert len(items) == 2
    assert all(item["batch_id"] == batch_id for item in items)
    assert {item["command_path"] for item in items} == {"echo"}

    response = admin_client.get(f"/batches/{batch_id}")
    assert response.status_code == 200
    assert "one" in response.get_data(as_text=True)

    response = admin_client.get("/api/batches")
    assert response.get_json()["data"]["total"] == 1

    response = admin_client.get("/batches/")
    assert response.status_code == 302
    assert f"/batches/{batch_id}" in response.headers["Location"]


def test_queue_delete_and_clear(admin_client, fixture_entry):
    data, _echo = payload(fixture_entry, "echo", text="x")
    item_id = admin_client.post("/api/queue", json=data).get_json()["data"][
        "queue_item_id"
    ]
    response = admin_client.delete(f"/api/queue/{item_id}")
    assert response.get_json()["status"] == 0
    assert admin_client.get("/api/queue").get_json()["data"]["total"] == 0

    admin_client.post("/api/queue", json=data)
    response = admin_client.delete("/api/queue")
    assert response.get_json()["status"] == 0
    assert admin_client.get("/api/queue").get_json()["data"]["total"] == 0


def test_upload(admin_client, config):
    response = admin_client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"upload-content"), "hello.txt")},
        content_type="multipart/form-data",
    )
    body = response.get_json()
    assert body["status"] == 0
    value = body["data"]["value"]
    assert Path(value).is_file()
    assert Path(value).read_text(encoding="utf-8") == "upload-content"
    assert body["data"]["filename"] == "hello.txt"


def test_bad_application_or_command(admin_client, fixture_entry):
    response = admin_client.post(
        "/api/execute", json={"_cliui_app": "missing", "_cliui_command": "n0"}
    )
    assert response.get_json()["status"] == 1

    response = admin_client.post(
        "/api/execute",
        json={"_cliui_app": fixture_entry.name, "_cliui_command": "nope"},
    )
    assert response.get_json()["status"] == 1

    response = admin_client.get("/?app=fixture&cmd=nope")
    assert response.status_code == 404


def test_create_app_with_multiple_entries(config, store, fixture_entry, single_entry):
    app = create_app(entries=[fixture_entry, single_entry], store=store, config=config)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    response = client.get("/?app=single")
    assert response.status_code == 200
    assert "single" in response.get_data(as_text=True)


def test_heading_shares_one_line_with_breadcrumb(admin_client, fixture_entry):
    run = node(fixture_entry, "sub run")
    page = page_json(
        admin_client.get(f"/?app=fixture&cmd={run.node_id}").get_data(as_text=True)
    )
    body_text = json.dumps(page, ensure_ascii=False)
    assert "cliui-hero-row" in body_text
    assert "(fixture / sub)" in body_text
    assert "cliui-reload-btn" in body_text


def test_reload_endpoint_refreshes_apps(admin_client, fixture_entry):
    response = admin_client.post("/api/reload")
    body = response.get_json()
    assert body["status"] == 0
    app_info = body["data"]["apps"][0]
    assert app_info["name"] == fixture_entry.name
    assert app_info["nodes"] == len(fixture_entry.nodes)
    assert app_info["commands"] >= 1

    # The console keeps serving pages with the swapped entries.
    assert admin_client.get("/").status_code == 200


def test_reload_requires_admin(web_app, store):
    store.create_user("bob", "bobpass")
    client = web_app.test_client()
    client.post("/login", data={"username": "bob", "password": "bobpass"})

    body_text = json.dumps(
        page_json(client.get("/").get_data(as_text=True)), ensure_ascii=False
    )
    assert "cliui-reload-btn" not in body_text

    response = client.post("/api/reload")
    assert response.status_code == 403
    assert response.get_json()["status"] == 1


def test_reload_picks_up_file_edits(tmp_path):
    source = tmp_path / "edited_cli.py"
    source.write_text(
        "import click\n"
        "@click.group()\n"
        "def cli():\n"
        "    pass\n"
        "@cli.command('one')\n"
        "def one():\n"
        "    pass\n",
        encoding="utf-8",
    )
    entry = load_app_entry(f"{source}:cli", str(tmp_path))
    assert any(item.name == "one" for item in entry.nodes.values())

    source.write_text(
        "import click\n"
        "@click.group()\n"
        "def cli():\n"
        "    pass\n"
        "@cli.command('two')\n"
        "def two():\n"
        "    pass\n",
        encoding="utf-8",
    )
    fresh = reload_app_entry(entry)
    assert fresh.name == entry.name
    assert any(item.name == "two" for item in fresh.nodes.values())
    assert not any(item.name == "one" for item in fresh.nodes.values())
