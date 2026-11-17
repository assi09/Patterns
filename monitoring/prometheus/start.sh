#!/bin/sh
# Starts Prometheus with its history on the volume at /prometheus (kept across restarts and
# redeploys) and the API's metrics token written to a private file, never into the image or git.
set -eu
: "${METRICS_TOKEN:?METRICS_TOKEN must equal the API's FA_METRICS_TOKEN}"
umask 077
printf '%s' "$METRICS_TOKEN" > /tmp/metrics-token
sed -e "s#__SCHEME__#${API_SCHEME:-https}#" \
    -e "s#__TARGET__#${API_TARGET:-api-production-eccff.up.railway.app}#" \
    /etc/prometheus/prometheus.template.yml > /tmp/prometheus.yml
exec /bin/prometheus \
  --config.file=/tmp/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time="${RETENTION:-90d}" \
  --web.listen-address=":${PROMETHEUS_PORT:-9090}"
