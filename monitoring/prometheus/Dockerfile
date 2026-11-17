# Prometheus for Patterns (docs/monitoring.md). Built from this folder, so the repository's
# railway.json (the API's) does not apply to it.
FROM prom/prometheus:v2.51.2
COPY prometheus.yml /etc/prometheus/prometheus.template.yml
COPY start.sh /start.sh
ENTRYPOINT ["/bin/sh", "/start.sh"]
