# Grafana for Patterns (docs/monitoring.md). Build from the repository root. Sign-in is required:
# no anonymous access, no sign-ups; the admin password comes from GF_SECURITY_ADMIN_PASSWORD.
FROM grafana/grafana:10.4.2
COPY monitoring/grafana/provisioning /etc/grafana/provisioning
COPY monitoring/grafana/dashboards /etc/grafana/dashboards
ENV GF_AUTH_ANONYMOUS_ENABLED=false \
    GF_USERS_ALLOW_SIGN_UP=false \
    GF_USERS_ALLOW_ORG_CREATE=false \
    GF_AUTH_BASIC_ENABLED=true \
    GF_ANALYTICS_REPORTING_ENABLED=false \
    GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    GF_SNAPSHOTS_EXTERNAL_ENABLED=false \
    GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/etc/grafana/dashboards/patterns.json \
    PROMETHEUS_URL=http://prometheus:9090
VOLUME ["/var/lib/grafana"]
