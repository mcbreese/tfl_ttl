---
title: tfl_ttl
---

# tfl_ttl

A data pipeline that polls the Transport for London Unified API twice a day,
lands the raw responses in S3, and models them with dbt on Athena into a star
schema for analytics.

**Status:** work in progress.

- Source code and setup: [GitHub repository](https://github.com/mcbreese/tfl_ttl)
- How it fits together: see the [README](https://github.com/mcbreese/tfl_ttl#readme)
