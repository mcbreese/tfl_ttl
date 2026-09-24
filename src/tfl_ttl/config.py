import os

from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = os.environ.get("S3_BUCKET")
S3_PREFIX = os.environ.get("S3_PREFIX", "raw/tfl")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
TFL_APP_KEY = os.environ.get("TFL_APP_KEY")
