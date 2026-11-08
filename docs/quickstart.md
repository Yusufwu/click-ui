# Quick start

This guide takes you from a fresh clone to a working console in a few minutes, then shows how to
point `click-ui` at your own Click application.

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
数据目录:   /path/to/click-ui/data
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
stdout/stderr and a link to the full record. Enable **后台执行** first when the command can take
a long time: the request returns immediately, the record starts as 执行中 and is filled in when
the command finishes (poll `GET /api/executions/<id>` if you need to watch it).

**Later** — press **加入队列** instead. The command is stored without running. Open
**记录队列**, reorder items with the arrow actions, then press **批量执行队列**. Each item
produces its own record and its own result row.

- Queued items survive restarts because they live in SQLite. Every batch run is stored as a
  batch record, and **执行批次** keeps the history with per-item results.

## 6. Schedule commands

Open any command, fill its form, then press **加入定时** (Add schedule). The plan dialog opens:

1. **周期（Cron）** — a five-field expression (`minute hour day month weekday`), e.g. `0 2 * * *`,
   or choose one of the presets.
2. **单次** — one timestamp in `YYYY-MM-DD HH:MM:SS` form.
3. **时区** — an IANA name, default `Asia/Shanghai`.
4. Optionally enable **停机补跑** so a fire missed while the scheduler was down is run once at
   startup.

Press **预览未来 3 次触发** to confirm the plan, then **加入定时** in the dialog footer. The
command arguments are submitted together with the dialog. Creating a schedule does not execute the
command immediately.

### Shell-only schedules

**新建定时** on the 定时任务 page opens a Shell dialog instead of navigating away. Type one shell
command per row (**新增** adds rows), up to 20 rows of 2000 characters each, pick a cron expression
or a one-off time, and press **创建定时**. Such plans are labelled `Shell` in the list and on the
detail page. They run as the operating-system user that runs cliui and skip Click entirely, so only
enter trusted commands.

### Multi-command plans, editing and copying

- A schedule is a **plan** with one or more commands. Fill a second command's form, pick the
  plan under **追加到已有计划** (Append to existing schedule) inside the same dialog, and press
  that button. Each trigger runs the commands in order and writes one execution record per
  command. Click commands and shell commands can live in the same plan.
- The **定时任务** list shows `首条命令 · 共 N 条`; open **详情** to see every command, remove
  one (at least one must remain), and edit the plan (cron / one-off time / time zone /
  catch-up). Saving recomputes the next run immediately.
- **复制** creates an independent copy of the plan, including its command list, so the same set
  of commands can run on several different schedules.

### Scheduler process

- **Development:** `cliui serve examples/demo_cli.py:cli --scheduler` starts the scheduler in a
  background thread inside the web process.
- **Production:** run it as its own process:

  ```bash
  cliui scheduler --data-dir data
  ```

  Omit the specs and the scheduler reuses the applications `cliui serve` registered in the
  database; pass specs explicitly if you prefer:

  ```bash
  cliui scheduler examples/demo_cli.py:cli --data-dir data
  ```

- **定时任务** page lists next/last run, status, enable/pause, run-now and delete. Regular users
  see only their own schedules; administrators see all.
- Fires missed while the scheduler was stopped are marked `missed` by default. Enable **停机补跑**
  per schedule to run once on the next start instead.
- Each fire is claimed atomically in SQLite, so running the standalone scheduler next to the web
  console never executes the same slot twice.

## 7. Uploads and output files

- `click.File(mode="r")` parameters render as file pickers. Files are uploaded to
  `<data-dir>/uploads` and passed to the command as a path.
- `click.Path` parameters accept typed paths and, when the file must exist, offer an upload
  helper that fills the field.
- `click.File(mode="w")` parameters are rendered as output paths; the command writes the file
  itself.

## 8. Data and backups

Everything persistent is under the data directory (default `./data`):

```
data/
  cliui.sqlite3     # users, execution records, queue, batches, schedules, app specs
  .secret_key       # generated Flask session key
  uploads/          # uploaded files
```

Back up the whole directory. Passing `--data-dir` (or `CLIUI_DATA_DIR`) lets you keep separate
console state per environment.

Large stdout/stderr is zlib-compressed once it exceeds 8 KB, so it is still stored as plain text
with a `cliui-gzip:` prefix and decoded transparently when read. To bound growth, pass
`--retention-days N` to `cliui serve` and/or `cliui scheduler`: records older than N days are
deleted on start-up (`0`, the default, keeps them forever).

## 9. Deploying behind a proxy

`cliui serve` uses Flask's development server, which is fine for a team tool on a trusted
network but not for the open internet. For a production-ish setup:

1. Configure an admin password through `CLIUI_ADMIN_PASSWORD` instead of passing it on the
   command line.
2. Run the console under a process manager (systemd, Supervisor, Windows service wrapper), and
   run `cliui scheduler` as a second supervised process that shares the same `--data-dir`.
3. Put it behind your SSO/VPN or a reverse proxy such as Nginx.
4. Restrict the host account's permissions to exactly what the CLI needs.

Example units:

```ini
# /etc/systemd/system/cliui-scheduler.service
[Unit]
Description=click-ui scheduler
After=network.target

[Service]
WorkingDirectory=/srv/click-ui
ExecStart=/srv/click-ui/.venv/bin/cliui scheduler --data-dir /srv/cliui-data
Restart=always

[Install]
WantedBy=multi-user.target
```

On Windows, create an NSSM service with the same arguments:

```powershell
nssm install click-ui-scheduler "C:\click-ui\.venv\Scripts\cliui.exe" "scheduler --data-dir C:\cliui-data"
nssm start click-ui-scheduler
```

With Docker, run the scheduler as a sidecar container that mounts the same data volume:

```bash
docker run -d --name cliui-scheduler \
  -v /srv/cliui-data:/data \
  click-ui:latest cliui scheduler --data-dir /data
```

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
