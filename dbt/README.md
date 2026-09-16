# dbt project (placeholder)

The dbt project that builds the Athena fact/dim tables from the S3-landed
TfL data will live in this directory, once the ingestion + EDA stages have
settled on a schema.

To scaffold it later:

```bash
pip install dbt-athena-community
dbt init tfl_ttl --profile tfl_ttl
```

Point the `tfl_ttl` profile in `~/.dbt/profiles.yml` at the Athena database
and S3 staging location configured in `.env` (`ATHENA_DATABASE`,
`ATHENA_OUTPUT_LOCATION`).
