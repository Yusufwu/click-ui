# Contributing

Thanks for taking the time to improve `cli-ui-amis`. This project aims to stay a thin,
read-only layer over Click, so contributions that preserve that property are especially welcome.

## Development setup

```bash
git clone <repository-url>
cd cli-ui-amis
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before opening a pull request

```bash
python -m pytest -q
```

All tests must pass. If you change generated forms or pages, add or update a test in
`tests/test_server.py` so the schema contract stays covered.

## What makes a good change

- **No Click intrusion.** Introspection may read Click objects, but must never patch, wrap or
  re-register them.
- **Server-rendered schemas.** New UI states belong in `cliui/web/pages.py` or
  `cliui/schema/`, not in ad-hoc browser JavaScript.
- **Friendly failures.** Validation errors should be readable and point at the offending field.
- **Small surfaces.** Prefer editing existing modules over adding new abstraction layers.

## Recipes

### Add support for a new parameter type

1. `cliui/introspect/params.py` — detect the type and set a `type_kind` plus any bounds,
   choices or options it needs.
2. `cliui/schema/fields.py` — render it as an AMIS control.
3. `cliui/schema/argv.py` — convert the submitted value back to Click-compatible argv.
4. `tests/fixtures/apps.py` — add a parameter to a fixture command.
5. `tests/` — assert both the rendered field and the produced argv.

### Add a page

Add a `build_*_page` function in `cliui/web/pages.py`, register the route in
`cliui/web/server.py`, and cover it with an authenticated request test.

### Report a bug

Please include:

- the Click snippet that reproduces it (or a link to the equivalent fixture)
- what the form rendered versus what you expected
- the produced argv / exit code and traceback if execution failed

## Code style

- Python 3.9-compatible syntax, `from __future__ import annotations` at the top of modules.
- Follow the existing module layout and naming; keep functions focused.
- Comments only where the reasoning is not obvious (for example, AMIS quirks such as
  `joinValues` / `extractValue`).
- No new runtime dependencies without discussing them first.

## License

By contributing you agree that your contribution is licensed under the Apache License 2.0.
