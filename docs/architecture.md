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
| `cliui/cli.py` | `cliui serve`, `cliui tree`, `cliui user` entry points |
| `cliui/config.py` | `Config` dataclass, environment variable fallbacks |
| `cliui/registry.py` | Loads `module:attr` / `file.py:attr` specs, validates the object is a Click command |
| `cliui/model.py` | `AppEntry`, `Node`, `ParamInfo`, `ExecutionResult` dataclasses |
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

AMIS form actions are fixed: **执行** posts to `/api/execute`, **加入队列** posts to `/api/queue`.
Neither depends on a client-side mode flag.

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

## Storage

SQLite tables (created on first start):

| Table | Contents |
| --- | --- |
| `users` | id, username, PBKDF2 password hash, admin flag, timestamps |
| `executions` | operator, app, node id, command path, params JSON, argv JSON, status, exit code, duration, stdout, stderr, exception, batch linkage |
| `queue_items` | operator, app, node id, label, params, created time, sort order |
| `batches` | operator, app, status, item count, timestamps |

All queries are scoped by `user_id`; administrators can list records across operators. Queue
operations (add, delete, move, clear) verify ownership before mutating.

## Web and auth

- `create_app(entries, store, config)` builds the Flask app; pages are rendered server-side into
  an AMIS `embed` payload, while the browser only loads the bundled AMIS SDK.
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
