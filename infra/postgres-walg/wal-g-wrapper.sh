#!/bin/sh
# Installed as /usr/local/bin/wal-g. Compose cannot leave an environment variable out when it is empty, and WAL-G
# treats an empty-but-set setting (e.g. AWS_ENDPOINT="", WALG_PGP_KEY_PATH="") as a real value, so drop those first.
for v in AWS_ENDPOINT AWS_S3_FORCE_PATH_STYLE AWS_REGION WALG_PGP_KEY_PATH; do
  eval "[ -n \"\${$v:-}\" ]" || unset "$v"
done
exec /usr/local/libexec/wal-g "$@"
