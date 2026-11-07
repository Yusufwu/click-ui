# Quick start

This guide takes you from a fresh clone to a working console in a few minutes, then shows how to
point `cli-ui-amis` at your own Click application.

## 1. Install

```bash
# from the repository root
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

Requirements: Python 3.9+, Click 8.1+, Flask 3. The AMIS SDK is bundled, so no network access is
needed at runtime.

Verify the installation:

```bash
cliui --version
```

## 2. Serve the demo

```bash
cliui serve examples/demo_cli.py:cli
```

Expected output:

```
已创建管理员账号：
  用户名: admin
  密码:   <generated password>
  请妥善保存，之后可在命令行用 `cliui user add` 创建更多账号。

已注册应用：
  - cli (cli) · 36 个命令节点
控制台地址: http://127.0.0.1:5000/
数据目录:   /path/to/cli-ui/data
```

Open `http://127.0.0.1:5000/`, log in with `admin` and the password shown above.

The demo covers the whole feature set:

- `text select` — `click.Choice` rendered as radio and checkbox groups
- `math range` — `IntRange` with enforced bounds
- `files info` — `click.Path` with existence validation
- `files read` — `click.File` with upload
- `system password` — `hide_input` rendered as a masked field
- `system uuid` — live UUID validation
- `pipeline` — a chained group that should be driven through the queue
- `legacy` — a deprecated command
- `greet` — a group with global options inherited by its children

Stop the server with `Ctrl+C`. Everything you executed remains in `data/cliui.sqlite3`.

## 3. Serve your own Click app

Any of these work:

```bash
# an installed module
cliui serve mypackage.cli:cli

# a single file on disk
cliui serve path/to/script.py:cli

# a nested attribute
cliui serve mypackage.cli:main.cli

# several apps at once, with custom display names
cliui serve tools/admin_cli.py:cli name=worker=tools/worker_cli.py:cli
```

Rules:

- `module:attr` uses Python import semantics; `file.py:attr` is loaded directly from disk.
- For file targets, the command's working directory is the file's directory. Relative
  `click.Path` arguments therefore resolve the same way they would when you run the script.
- Use `name=pkg.cli:cli` to control how the app appears when serving multiple apps.
- One spec or many, the console groups them in the top bar.

Check what the console will see without starting a server:

```bash
cliui tree mypackage.cli:cli
cliui tree mypackage.cli:cli --json
```

## 4. Accounts

The first `cliui serve` creates `admin`. To add more operators:

```bash
cliui user add ops                       # prompts for a password
cliui user add ops-admin --admin         # administrator role
cliui user list
```

Regular users only see their own execution records. Administrators can list and filter records
from every operator.

If you lose the initial password, create a new administrator account:

```bash
cliui user add rescue --admin
```

Both commands operate on `./data` by default; pass `--data-dir` if the server uses a different
directory.

## 5. Execute, queue, and batch

**Run now** — fill the form and press **执行**. The result panel shows exit code, duration,
stdout/stderr and a link to the full record.

**Later** — press **加入队列** instead. The command is stored without running. Open
**记录队列**, reorder items with the arrow actions, then press **批量执行队列**. Each item
produces its own record and its own result row.

- Queued items survive restarts because they live in SQLite. Every batch run is stored as a
  batch record, and **执行批次** keeps the history with per-item results.

## 6. Uploads and output files

- `click.File(mode="r")` parameters render as file pickers. Files are uploaded to
  `<data-dir>/uploads` and passed to the command as a path.
- `click.Path` parameters accept typed paths and, when the file must exist, offer an upload
  helper that fills the field.
- `click.File(mode="w")` parameters are rendered as output paths; the command writes the file
  itself.

## 7. Data and backups

Everything persistent is under the data directory (default `./data`):

```
data/
  cliui.sqlite3     # users, execution records, queue, batches
  .secret_key       # generated Flask session key
  uploads/          # uploaded files
```

Back up the whole directory. Passing `--data-dir` (or `CLIUI_DATA_DIR`) lets you keep separate
console state per environment.

## 8. Deploying behind a proxy

`cliui serve` uses Flask's development server, which is fine for a team tool on a trusted
network but not for the open internet. For a production-ish setup:

1. Configure an admin password through `CLIUI_ADMIN_PASSWORD` instead of passing it on the
   command line.
2. Run the console under a process manager (systemd, Supervisor, Windows service wrapper).
3. Put it behind your SSO/VPN or a reverse proxy such as Nginx.
4. Restrict the host account's permissions to exactly what the CLI needs.

If you prefer a WSGI server, wrap the app factory yourself:

```python
# wsgi.py
from cliui.config import build_config
from cliui.registry import load_app_entry
from cliui.storage.repo import Store
from cliui.web.server import create_app

entry = load_app_entry("mypackage.cli:cli", base_cwd=".")
config = build_config(data_dir="/srv/cliui-data")
store = Store(config.db_path)
store.ensure_admin(config.admin_password or "change-me")
app = create_app(entries=[entry], store=store, config=config)
```

```bash
pip install waitress
waitress-serve --port 8080 wsgi:app
```

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `应用地址缺少属性名` | Use `module:attr` or `file.py:attr`, not just a module name |
| `找不到属性 ...` | The attribute after `:` does not exist or is not exported |
| `不是 click.Command（实际类型 ...）` | Point at the `click.Group`/`Command` object, not the function |
| `导入模块 ... 失败` | The module raises on import; run it directly to see the traceback |
| Login fails after restart | The password is printed only on first creation; add a new admin with `cliui user add rescue --admin` |
| `click.Path` says a file is missing | Paths resolve relative to the app file's directory; enter a path relative to that directory |
| Port already in use | Pass another `--port` |
| Pages look unstyled | Ensure the package data is available (`pip install -e .` serves the bundled assets from the source tree) |
