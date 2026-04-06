# Python Coding Standards

Lines are never longer than 100 characters.
Use 4 spaces for indentation.
Always use type hints for function signatures.
Use `snake_case` for variable and function names, and `PascalCase` for class names.

## Logging — Use `loguru` instead of `print`

Never use `print()` for output or debugging. Always use `loguru`'s `logger`.

```python
# BAD
print("Starting scrape...")
print(f"Error: {e}")

# GOOD
from loguru import logger

logger.info("Starting scrape...")
logger.error(f"Error: {e}")
```

## File Paths — Use `pathlib.Path` instead of `os.path`

Always use `pathlib.Path` for file and directory operations. Do not use `os.path`.

```python
# BAD
import os
config_path = os.path.join(base_dir, "config", "settings.yml")
if os.path.exists(config_path):
    ...

# GOOD
from pathlib import Path

config_path = Path(base_dir) / "config" / "settings.yml"
if config_path.exists():
    ...
```

## After Every Code Change — Run Tests and Update Docs

After any code change:

1. **Run the test suite** — `uv run pytest`. All tests must pass before the task is considered done.
2. **Update tests** — every modified function must have its test updated or extended to cover the new behaviour.
3. **Update README.md** — if the change affects a CLI command, flag, or user-facing behaviour, document it in README.md.

## Testing — Always write unit tests

Every module and function must have corresponding unit tests. Use `pytest` as the test framework. Place tests in a `tests/` directory mirroring the source structure.

Always use `pytest.param` with `id` for parameterized test cases.

```python
# BAD
@pytest.mark.parametrize("input_val, expected", [
    ("input1", "output1"),
    ("input2", "output2"),
])
def test_my_function(input_val, expected):
    assert my_function(input_val) == expected

# GOOD
@pytest.mark.parametrize("input_val, expected", [
    pytest.param("input1", "output1", id="handles-basic-input"),
    pytest.param("input2", "output2", id="handles-alternate-input"),
])
def test_my_function(input_val, expected):
    assert my_function(input_val) == expected
```

## Dependencies — Pin with upper bound on major version

```toml
# BAD
dependencies = [
    "loguru",
    "httpx==0.27.0",
    "beautifulsoup4>=4.12",
]

# GOOD
dependencies = [
    "loguru>=0.7.3,<1",
    "httpx>=0.27.0,<1",
    "beautifulsoup4>=4.12.3,<5",
]
```

## Odoo Custom Field Naming

All custom fields on Odoo Studio models must follow these conventions:

### Relation fields
- **many2one** and **one2many**: `x_<related_model_name>_id`
  - e.g. many2one to `x_gear` → `x_gear_id`
  - e.g. many2one to `x_models` → `x_models_id`
- **many2many**: `x_<related_model_name>_ids`
  - e.g. many2many to `x_custom_build_part` → `x_custom_build_part_ids`
- For standard Odoo models (`res.currency`, `res.partner`), use `x_<purpose>_id` (e.g. `x_currency_id`, `x_partner_id`)

### Boolean fields
Boolean fields must be prefixed with `is_`, `has_`, or `can_` to make their true/false nature explicit:
- `x_is_keeper`, `x_is_taxed`, `x_is_custom_build`
- `x_has_forwarding`
- `x_can_accept_offers`

### `conn.get_model()` and model name forms
Two rules depending on model origin:

**Custom `x_` models** — always use **underscored** form everywhere:
- `conn.get_model("x_gear")`
- `ir.model` domain: `[("model", "=", "x_gear")]`
- `ir.model.fields` relation value: `"relation": "x_gear"`, `"relation": "x_models"`

**Standard Odoo models** (`res.currency`, `res.partner`, etc.) — always use **dotted** form in `relation`:
- `"relation": "res.currency"`, `"relation": "res.partner"`
- `conn.get_model("res.currency")` (unchanged — dotted is correct here too)

Getting this wrong causes silent `False` results or a `ValidationError: Unknown model name` with no other context.

## Running Python — Always use `uv`

Always use `uv` to run Python code and manage dependencies.

```bash
# Running a script
uv run python script.py

# Adding a dependency
uv add package_name

# Running tests
uv run pytest
```
