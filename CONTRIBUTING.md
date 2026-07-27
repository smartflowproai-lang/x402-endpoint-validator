# Contributing to x402-validator

The conformance engine is the core IP of this project. Adding checks is welcome;
changing existing checks risks breaking downstream operators who pin to a version.

## Local setup

```bash
git clone https://github.com/smartflowproai-lang/x402-endpoint-validator
cd x402-endpoint-validator
python -m venv venv && source venv/bin/activate
pip install -e ".[all]"
pip install pytest pytest-asyncio pytest-cov
```

## Run the test suite

```bash
# Functional only
pytest tests/ -v

# With coverage (must hit 100% on the engine)
pytest tests/test_engine.py --cov=x402_validator/_engine --cov-report=term-missing
```

Coverage must remain at **100%** for `x402_validator/_engine/`. If your PR adds a
branch without a test, CI will fail.

## How checks are structured

Each check is one `async def` in `x402_validator/_engine/checks.py`, returning a
Pydantic model from `x402_validator/_engine/models.py`. Human messages live in
`messages.py` — checks never inline text.

```
def check_<name>(client, ...) -> SomeResult:
    try:
        ...
        return SomeResult(status="PASS", message=msg.pass_text(), details={...})
    except ...:
        return SomeResult(status="ERROR", message=msg.error_text(), details={...})
```

## Adding a new check

1. **Define a Pydantic model** in `x402_validator/_engine/models.py`:

   ```python
   class MyNewResult(CheckResult):
       check_name: Literal["my_new_check"] = "my_new_check"
   ```

2. **Add message builders** in `messages.py` — both PASS and FAIL variants. Each
   message must specify what the operator should fix.
3. **Add the check function** in `checks.py`. Single responsibility, ≤60 lines.
4. **Wire it into `X402Auditor.run_full_audit()`** (or the marketplace helper).
5. **Write at least 6 tests** in `tests/test_engine.py`:
   - happy path
   - one FAIL variant
   - one CRITICAL_FAIL variant (if applicable)
   - one ERROR / timeout
   - one malformed-input case
   - one edge case (boundary value, empty, oversized)
6. **Run the full suite** — `pytest tests/test_engine.py -v --cov=x402_validator/_engine`.

## Rules for check messages

- **Never** write `"check failed"`. Write the operator-actionable equivalent:
  - `"Payment-Required header missing. Expected: 'X-Payment-Required: '. Found: none."`
  - `"Bazaar extension not implemented (optional). To add: include 'extensions.bazaar' in HTTP 402 response body with fields: method, serviceName, tags."`
- Each FAIL must name the offending field.
- Each CRITICAL_FAIL must explain downstream impact (e.g. "this crashes the reference verifier").
- Each ERROR must describe what the operator should check (URL, network, etc.).

## Submitting a PR

- Branch prefix: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`.
- Include pytest output in the PR description: `XX passed in 0.5s` is not
  enough; paste the failing-then-passing run before and after your change.
- Update `CHANGELOG.md` under `[Unreleased]` with one bullet per PR.
- Squash-merge into `main`.

## Adding a new report format (CSV, JSON, HTML)

Report formats live in `x402_validator/cli.py`. Each writer is a `def write_X(reports, path) -> None`
function. The CLI dispatcher validates the format name against `writers.keys()`.
Do not change the JSON shape without bumping the major version.

## Breaking change policy

Anything in `x402_validator/_engine/__init__.py`, `x402_validator/cli.py`, or
`x402_validator/mcp_server.py` is public. Renaming a function, changing a
return type, or removing a status literal is a **breaking change** and
requires bumping the major version and a CHANGELOG entry.

Internal modules (anything whose name starts with `_`) are not public and can
be changed without a major bump.
