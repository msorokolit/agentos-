#!/usr/bin/env sh
# One-shot MinIO bootstrap script.
# - Waits for MinIO to be reachable
# - Creates the AgenticOS bucket (idempotent)
# - Applies a 365-day lifecycle rule to expire processed documents
# - Enables versioning so accidental deletes are recoverable for 7 days

set -eu

ALIAS=agenticos
ENDPOINT="${S3_ENDPOINT:-http://minio:9000}"
ACCESS_KEY="${S3_ACCESS_KEY:-agenticos}"
SECRET_KEY="${S3_SECRET_KEY:-agenticos-minio}"
BUCKET="${S3_BUCKET:-agenticos}"
DOCUMENT_TTL_DAYS="${S3_DOCUMENT_TTL_DAYS:-365}"
NONCURRENT_TTL_DAYS="${S3_NONCURRENT_TTL_DAYS:-7}"

echo "==> waiting for ${ENDPOINT}..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if mc alias set "$ALIAS" "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
mc alias set "$ALIAS" "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY"

echo "==> ensuring bucket ${ALIAS}/${BUCKET}"
mc mb --ignore-existing "${ALIAS}/${BUCKET}"

echo "==> enabling versioning"
mc version enable "${ALIAS}/${BUCKET}" || true

echo "==> applying lifecycle (expire after ${DOCUMENT_TTL_DAYS}d, noncurrent ${NONCURRENT_TTL_DAYS}d)"
cat >/tmp/lifecycle.json <<JSON
{
  "Rules": [
    {
      "ID": "expire-processed-documents",
      "Status": "Enabled",
      "Filter": { "Prefix": "documents/" },
      "Expiration": { "Days": ${DOCUMENT_TTL_DAYS} }
    },
    {
      "ID": "expire-tmp",
      "Status": "Enabled",
      "Filter": { "Prefix": "tmp/" },
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "noncurrent-cleanup",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "NoncurrentVersionExpiration": { "NoncurrentDays": ${NONCURRENT_TTL_DAYS} }
    },
    {
      "ID": "abort-incomplete-multiparts",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    }
  ]
}
JSON
mc ilm import "${ALIAS}/${BUCKET}" </tmp/lifecycle.json
echo "==> done."
