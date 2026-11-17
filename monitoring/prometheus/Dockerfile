# Prometheus for Patterns (docs/monitoring.md). Build from the repository root.
FROM prom/prometheus:v2.51.2
COPY monitoring/prometheus/prometheus.yml /etc/prometheus/prometheus.template.yml
COPY monitoring/prometheus/start.sh /start.sh
VOLUME ["/prometheus"]
ENTRYPOINT ["/bin/sh", "/start.sh"]
