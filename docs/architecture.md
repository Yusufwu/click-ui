# Architecture

`click-ui` is a thin, read-only layer around Click. It never monkey-patches Click, never
rewrites your commands and never imports side effects into your CLI's runtime behaviour. This
document explains how the pieces fit together and where to extend them.

## Pipeline

```
module:cli
   │  registry.load_app_entry()
   ▼
AppEntry ── introspect.tree.build_tree() ──► Node / ParamInfo model
   │                                            │
   │                    schema.form.build_form_schema()
   │                    schema.nav / pages
   ▼                                            ▼
Flask routes  ◄──────────── AMIS JSON ────────► Browser
   │
   │  POST /api/execute (form values)
   ▼
schema.argv.build_argv() ── validate ──► execute.runner.run()
   │                                        │
   ▼                                        ▼
SQLite records / queue / batches        stdout · stderr · exit code · duration
```

## Modules

| Path | Responsibility |
| --- | --- |
| `cliui/cli.py` | `cliui serve`, `cliui scheduler`, `cliui tree`, `cliui user` entry points |
| `cliui/config.py` | `Config` dataclass, environment variable fallbacks |
| `cliui/registry.py` | Loads `module:attr` / `file.py:attr` specs, validates the object is a Click command |
| `cliui/model.py` | `AppEntry`, `Node`, `ParamInfo`, `ExecutionResult` dataclasses |
| `cliui/scheduling.py` | Cron / one-off scheduling, shared by the web thread and the standalone process (no Flask imports) |
| `cliui/introspect/` | Walks command trees and extracts parameter metadata |
| `cliui/schema/` | Builds AMIS JSON (nav, forms, pages) and converts form values to argv |
| `cliui/execute/` | In-process execution through `click.testing.CliRunner` |
| `cliui/storage/` | SQLite schema and repository (`Store`) |
| `cliui/web/` | Flask app factory, routes, pages, auth, bundled AMIS assets |

## Introspection

`introspect.tree.build_tree()` recursively walks a `click.Command`:

- `Group.list_commands()` / `get_command()` are used, so lazy groups work.
- `CommandCollection` sources are flattened into one tree.
- Each command becomes a `Node` with a stable, traversal-order id (`n0`, `n1`, …). These ids
  are what `?app=...&cmd=nXX` routes use; `cliui tree --json` prints them for debugging.
- `hidden=True` commands are still loaded into `entry.nodes` (so links keep working) but are
  excluded from the generated navigation.
- `deprecated=True`, `chain=True` and `allow_extra_args` become notes shown on the form.

`introspect.params.describe_param()` extracts:

- label (explicit `metavar`, otherwise a humanized name), help/description fragments
- `name` (the Click destination), option strings, argument position
- default value (callable defaults are invoked defensively)
- `required`, `multiple`, `nargs`, `envvar`, `prompt`, `hide_input`
- a normalized `type_kind`: `text`, `int`, `float`, `bool`, `choice`, `tuple`, `file`, `path`,
  `datetime`, `uuid`, `count`
- range bounds for `IntRange` / `FloatRange`, choice options and tuple element types

Help and version options are skipped, as are parameters that Click never exposes to callbacks.

## Schema generation

Forms are generated server-side, which keeps the browser thin and makes every page testable with
plain HTTP assertions.

- Navigation is an AMIS `nav` tree built from the command tree.
- Each command form uses horizontal layout, with global options separated from command options.
  Hidden parameters live in an advanced section.
- Each field carries `name` prefixed with `c__` to avoid clashes with the form's internal state,
  plus a stable `description` that repeats the exact CLI spelling.
- `Choice` → `radios`; `Choice(multiple=True)` → `checkboxes` with `joinValues: false` and
  `extractValue: true`, so AMIS submits a clean list of values instead of a joined string or
  full option objects.
- `File` (read) → `input-file` backed by `/api/upload`; `Path` → text plus an upload helper that
  fills the field; `File` (write) → output path input.
- `hide_input` → `input-password`; `UUID` → text with a `matchRegexp` validation and a friendly
  `validationErrors` message.
- Array-ish parameters (`multiple`, `nargs != 1`, tuples) → `input-array` with sensible
  `minLength` / `maxLength`.

AMIS form actions are fixed: **执行** posts to `/api/execute`, **加入队列** posts to
`/api/queue`. **加入定时** opens an AMIS dialog instead: the plan fields (cron / one-off time /
time zone / catch-up / append target) live in the dialog itself, while hidden `mirror__*` fields
carry the command form values into the dialog. The footer submit posts to `/api/schedules`, the
preview button to `/api/schedules/preview`, and **确认追加** (after picking a plan in the
**追加到已有计划** selector) to `/api/schedules/<id>/items`. The server strips the `mirror__`
prefix before validation. Because AMIS renders a dialog body form's own `actions` unreliably, all
dialog buttons are declared in `dialog.actions` (footer) or as ordinary form body items, never in
the form's `actions` array.

The 定时任务 page's **新建定时** opens a second dialog that collects up to 20 raw shell commands
(`POST /api/schedules/shell`) and stores them as `{kind: "shell", shell, ...}` plan items next to
regular `{kind: "command", app, command, argv}` items.

## argv conversion and validation

`schema.argv.build_argv()` turns submitted values into a `list[str]`. It walks the command
ancestors from the root group down to the selected command. For each scope it emits options
first, then positional arguments, then the next command name:

```
[root options] [root args] <child> [child options] [child args] <grandchild> ...
```

Details that matter:

- The root command name itself is not part of the argv; the preview prepends it for display.
- A `--` terminator is inserted before positional values that start with `-`, so Click cannot
  mistake a positional value for an option.
- `--flag/--no-flag` pairs emit either the positive or the negated option.
- Boolean switches emit `True`/`False` only when the option is not a flag.
- `multiple=True` options repeat the option once per value; `Tuple` values are flattened into
  consecutive tokens; `nargs=-1` arguments are expanded.
- Empty optional values are omitted; empty required values produce a field-level error.
- Validation happens before execution: int/float ranges, choice membership, UUID shape,
  nargs arity and required arguments all return friendly messages (`字段 的可选值: ...`).
- The preview uses the same conversion, so what you see is exactly what Click receives.

## Execution

`execute.runner.run()`:

- calls `CliRunner(mix_stderr=False)` so stdout and stderr stay separable
- temporarily `chdir`s to the app file's directory (restoring the previous cwd afterwards), so
  relative `click.Path` / `click.File` behave exactly as when the script is run directly
- holds a process-wide lock: command execution is **serialized**, which avoids chdir races and
  stdout/signal interleaving
- captures exit code, duration, stdout, stderr and exception text, truncating each stream to
  `max_output_chars`
- translates `ClickException` / `Abort` into readable messages instead of just exit codes

There is no per-command timeout. A CLI that hangs will hold the executor lock; make sure your
commands terminate.

The lock is shared by web requests and scheduled fires. Web requests wait for it indefinitely;
the scheduler passes `wait_seconds` and, if the lock is still busy, records the run as
`skipped` instead of delaying the next job.

## Storage

SQLite tables (created on first start):

| Table | Contents |
| --- | --- |
| `users` | id, username, PBKDF2 password hash, admin flag, timestamps |
| `executions` | operator, app, node id, command path, params JSON, argv JSON, status, exit code, duration, stdout, stderr, exception, batch linkage, trigger (`manual` / `schedule`), schedule id |
| `queue_items` | operator, app, node id, label, params, created time, sort order |
| `batches` | operator, app, status, item count, timestamps |
| `schedules` | one or more commands in `items_json` (app, command path, argv, params, label), plus the first item mirrored into the legacy single-command columns; cron or run-at, timezone, catch-up flag, enabled, creator, next/last run, last status, last execution id |
| `command_favorites` | operator, app, command path (the ★ state on `/overview`) |
| `app_specs` | registered `module:attr` specs and base working directories, published by `serve` for the standalone scheduler |

All queries are scoped by `user_id`; administrators can list records across operators. Queue
operations (add, delete, move, clear) verify ownership before mutating; schedules use
`created_by` for the same check.

Schema changes are applied in place: `init_db()` runs `PRAGMA table_info` against existing tables
and adds new columns with `ALTER TABLE` (for example `executions.trigger`,
`executions.schedule_id` and `schedules.items_json`), so an existing data directory keeps working
after an upgrade. Rows created before `items_json` are normalized by `schedule_items()` into a
single-item plan.

Large stdout/stderr (>8 KB) is zlib-compressed and stored as `cliui-gzip:<base64>` text,
transparently decoded on read, which keeps the column type and avoids a BLOB migration.
`--retention-days N` calls `purge_executions()` at start-up; `0` disables pruning.

## Scheduling

`cliui/scheduling.py` owns everything time-related and imports no Flask, so the same code runs
inside `cliui serve --scheduler` (background thread) and in the standalone `cliui scheduler`
process.

- `validate_schedule()` accepts either a five-field cron expression (`CronTrigger.from_crontab`)
  or a single run-at timestamp, validates the IANA time zone, and normalizes both.
- `next_fire_times()` asks the trigger for the next N fires without sleeping; the form preview
  and the API share this path, which keeps tests fast and deterministic.
- `SchedulerService` builds a `BackgroundScheduler` or `BlockingScheduler`, loads enabled rows
  from `schedules`, and keeps `next_run_at` in sync. UI changes call `sync()` to rebuild jobs.
- Schedules store the command **path** (`system password`), not the traversal node id, because
  node ids shift whenever the command tree changes. At fire time the scheduler resolves the
  path against freshly loaded apps; a removed app or command produces a failed execution record.
- `claim_schedule_run()` is a conditional update
  (`WHERE id = ? AND enabled = 1 AND next_run_at = ?`). Exactly one process wins a slot; a stale
  `next_run_at` means another process already handled it.
- On startup `recover_missed()` marks overdue schedules as `missed`, or — when catch-up is
  enabled — claims and runs them once.
- A scheduled fire skips the form/argv layer: for each stored plan item the argv goes straight to
  `execute_command()`, and one record per item is written with `trigger='schedule'` and
  `schedule_id`. The overall status is `failed` > `skipped` > `success`.
- Plans can be edited (`update_schedule_plan()` recomputes `next_run_at` and calls `sync()`),
  duplicated (`duplicate_schedule()` copies every item into a new row) and extended/trimmed
  (`add_schedule_item()` / `remove_schedule_item()`, which keeps at least one item).
- `serve` publishes its registered specs into `app_specs`, so `cliui scheduler --data-dir ...`
  can start without repeating the application arguments.

## Web and auth

- `create_app(entries, store, config)` builds the Flask app; pages are rendered server-side into
  an AMIS `embed` payload, while the browser only loads the bundled AMIS SDK.
- Pages: `/` (console), `/overview` (all commands with one-line help, search, favourites and
  recents, reachable by clicking the CLI badge), `/records`, `/queue`, `/batches`, `/schedules`,
  `/schedules/<id>` (plan detail: items, edit form, copy, recent runs).
- Schedules API: `POST /api/schedules` (create), `POST /api/schedules/preview`,
  `GET /api/schedules`, `POST /api/schedules/<id>/run`, `POST /api/schedules/<id>/toggle`,
  `POST /api/schedules/<id>/edit`, `POST /api/schedules/<id>/duplicate`,
  `POST /api/schedules/<id>/items`, `DELETE /api/schedules/<id>/items/<index>`,
  `DELETE /api/schedules/<id>`; ownership is checked with `require_schedule_owned`.
- `POST /api/execute` accepts `background=1`: it writes a `running` record, starts a daemon
  thread, and returns immediately. The thread calls `update_execution_result()` when done.
  `GET /api/executions/<id>` exposes the same record for polling. Execution is in-process, so a
  running command cannot be cancelled from the UI; it stops with the server process.
- `/overview/favorite` toggles a favourite and redirects back (preserving the `q` search term).
- Sessions use an HMAC-signed cookie (`HttpOnly`, `SameSite=Lax`, 7-day lifetime) and a secret
  key persisted in the data directory.
- HTML routes use `login_required`; JSON APIs use `api_login_required`, which returns 401 JSON
  instead of a login page.
- `before_request` resolves the current user into `g.user`; record/queue access is ownership
  checked (`require_owned`).
- Uploads are authenticated, size limited (`max_upload_mb`) and stored with sanitized names
  under `<data-dir>/uploads`.

## Testing

`tests/` contains pytest suites for introspection, argv building, validation, execution, storage,
HTTP routes and generated page structure. Browser-level behaviour (login, radio/checkbox
submission, uploads, queue and batch flows) is covered with Playwright against a real server
during development; `tests/test_server.py` is the closest CI-friendly equivalent.

## Where to extend

- **New parameter kind**: add a `type_kind` in `introspect/params.py`, a field branch in
  `schema/fields.py`, a conversion branch in `schema/argv.py`, and a test fixture in
  `tests/fixtures/apps.py`.
- **New page or panel**: build it in `web/pages.py` and register a route in `web/server.py`.
- **New storage feature**: add a table in `storage/repo.py` with ownership-scoped queries, then
  expose it through a page and an API route.
