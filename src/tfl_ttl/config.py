# Settings for the pipeline, read from the environment.
#
# Everything here runs once, the first time any module imports config.
# Python caches the module, so later imports reuse the same values for the
# life of the process.

import os

from dotenv import load_dotenv

# With no path, load_dotenv() walks up from this file's folder until it finds
# a .env, so it works wherever Python is launched from (unlike "../.env",
# which is relative to the launch folder). No .env, as in GitHub Actions,
# means it silently loads nothing.
#
# It never overwrites a variable that already exists (override=False).
# Values set in the terminal or by GitHub Actions secrets always beat .env,
# so a stray .env can't redirect a real run.
load_dotenv()

# os.environ.get returns None (or the given default) when a variable is
# missing, instead of raising.

# No default on purpose: guessing a bucket is worse than failing.
# __main__.run() checks it's set before polling anything.
S3_BUCKET = os.environ.get("S3_BUCKET")
S3_PREFIX = os.environ.get("S3_PREFIX", "raw/tfl")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")

# If missing, requests still work but go out unauthenticated at TfL's lower
# rate limit. Nothing errors; you'd only notice through 429 responses.
TFL_APP_KEY = os.environ.get("TFL_APP_KEY")

# AWS credentials are deliberately not read here. boto3 finds them itself,
# in order: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars, then a named
# profile, then a role on the machine. Note AWS_PROFILE is an instruction,
# not a hint: if it names a profile that doesn't exist, boto3 raises
# ProfileNotFound instead of moving on to the next option.
