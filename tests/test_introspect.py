from __future__ import annotations


def find_node(entry, path: str):
    for node in entry.nodes.values():
        if node.path == path:
            return node
    raise AssertionError(f"node not found: {path}")


def test_tree_shape_and_node_ids(fixture_entry):
    root = fixture_entry.root
    assert root.node_id == "n0"
    ids = list(fixture_entry.nodes)
    assert len(ids) == len(set(ids))
    assert all(node_id.startswith("n") for node_id in ids)

    echo = find_node(fixture_entry, "echo")
    run = find_node(fixture_entry, "sub run")
    assert echo.parent is fixture_entry.root
    assert run.parent is find_node(fixture_entry, "sub")
    assert echo.path == "echo"
    assert run.level == 2
    assert run.executable
    assert not find_node(fixture_entry, "sub").executable


def test_help_options_are_not_form_parameters(fixture_entry):
    keys = [param.key for param in fixture_entry.root.params]
    assert keys == ["root_name", "verbose"]
    assert fixture_entry.root.params[0].label == "Root Name"
    verbose = fixture_entry.root.params[1]
    assert verbose.count
    assert not verbose.is_flag
    assert verbose.type_kind == "count"


def test_hidden_commands_are_loaded_but_not_navigable(fixture_entry):
    secret = find_node(fixture_entry, "secret")
    assert secret.hidden
    assert secret in fixture_entry.nodes.values()
    assert secret not in fixture_entry.root.children


def test_param_metadata(fixture_entry):
    run = find_node(fixture_entry, "sub run")
    params = {param.key: param for param in run.params}
    assert params["flag"].is_flag
    assert params["flag"].secondary_opts == ["--no-flag"]
    assert params["level"].type_kind == "int_range"
    assert params["level"].min == 1 and params["level"].max == 10
    assert params["ratio"].type_kind == "float_range"
    assert params["mode"].type_kind == "choice"
    assert params["mode"].choices == ["a", "b"]
    assert params["mode"].case_sensitive is False
    assert params["tag"].multiple
    assert params["pair"].nargs == 2
    assert params["value"].is_argument
    assert "group" not in params


def test_lazy_group_is_resolved(lazy_entry):
    dynamic = find_node(lazy_entry, "dynamic")
    assert dynamic.command is not None
    assert lazy_entry.root.children[0].name == "dynamic"
    assert dynamic.level == 1


def test_command_collection_merges_sources(collection_entry):
    paths = {node.path for node in collection_entry.nodes.values()}
    assert "one" in paths
    assert "two" in paths
    assert collection_entry.root.command_collection


def test_single_command_app(single_entry):
    assert not single_entry.root.is_group
    assert single_entry.root.executable
    assert single_entry.root.node_id == "n0"
    assert single_entry.default_node() is single_entry.root
