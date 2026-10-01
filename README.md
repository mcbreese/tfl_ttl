# tfl_ttl

Pipeline that ingests data from the TfL (Transport for London) Unified API,
lands it in S3, models it with dbt into fact/dim tables in Athena, and
serves BI + conversational analytics on top.

## Pipeline stages

```
TfL API  -->  ingestion scripts  -->  S3 (raw)  -->  dbt  -->  Athena (fact/dim)  -->  BI / conversational analytics
```

1. **Ingestion** (`src/tfl_ttl/ingestion/`) — scripts that call the TfL
   Unified API and write the raw JSON responses to S3.
2. **Storage** (`src/tfl_ttl/aws/`) — S3 upload helpers; raw data is landed
   under a date-partitioned prefix for Athena to read.
3. **Modeling** (`dbt/`) — dbt project transforming raw S3 data (via an
   Athena/Glue external table) into fact and dimension tables.
4. **Consumption** — the Athena output tables feed BI tooling and a
   conversational analytics layer.

## Repo layout

```
notebooks/        EDA notebooks (start here)
src/tfl_ttl/       Shared Python package
  config.py        Env-based configuration
  ingestion/       TfL API client + ingestion scripts
  aws/             S3 upload helpers
dbt/               dbt project (scaffolded once EDA settles the schema)
data/
  raw/             Local raw data samples (gitignored)
  processed/       Local processed/EDA outputs (gitignored)
config/            Non-secret pipeline config
tests/             Unit tests for src/tfl_ttl
```

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync
copy .env.example .env
```

Fill in `.env` with TfL app credentials (optional, raises rate limits) and
your AWS profile/region/bucket once ingestion moves past EDA.

## Linting and formatting

CI (`.github/workflows/ci.yml`) runs ruff and the tests on every PR and push
to `master`.
Run the same checks locally before pushing:

```bash
uv run ruff check .          # lint (add --fix to auto-fix)
uv run ruff format .         # format
```

Rules and line length live under `[tool.ruff]` in `pyproject.toml`.
Notebooks are excluded.

### Pre-commit hooks

The same ruff checks run automatically on each commit once the hooks are
installed. Do this once per clone:

```bash
uv run pre-commit install
uv run pre-commit run --all-files   # optional: check everything now
```

Hooks can be skipped with `--no-verify`, so CI is still the real gate.

### Notebooks and secrets

The `nbstripout` hook strips cell outputs from notebooks on commit. A
printed API response can carry an app key or personal data, and outputs
also make diffs noisy. Two things it does not cover:

- **Secrets typed into code cells.** Load credentials from `.env` (see
  `config.py`) and never paste them into a cell.
- **Skipped hooks.** A commit made with `--no-verify` keeps its outputs.

## Tests

```bash
uv run pytest                        # all tests, with the coverage report
uv run pytest tests/test_feeds.py    # one file
uv run pytest -v                     # list each test by name
uv run pytest --no-cov -x            # stop at the first failure, skip coverage
```

There's one test file per module in `src/tfl_ttl/`, plus shared fixtures in
`tests/conftest.py`. No test touches TfL or AWS: the network and boto3 are
faked, and an autouse fixture swaps in dummy AWS credentials.

Coverage must stay at 100% (`fail_under` in `pyproject.toml`), and CI runs the
suite on Python 3.10 and 3.13. 100% means every line ran, not that every
behaviour is checked, so new code still needs tests that assert something.

## Current stage: EDA

```bash
uv run jupyter lab
```

Open [notebooks/01_tfl_api_eda.ipynb](notebooks/01_tfl_api_eda.ipynb) to
explore the TfL API directly.
