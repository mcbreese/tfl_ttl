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

## Current stage: EDA

```bash
uv run jupyter lab
```

Open [notebooks/01_tfl_api_eda.ipynb](notebooks/01_tfl_api_eda.ipynb) to
explore the TfL API directly.
