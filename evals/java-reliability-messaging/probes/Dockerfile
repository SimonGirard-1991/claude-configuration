# PostgreSQL 18.6 with pg_cron and PgBouncer from the PGDG repository the image already uses.
# concurrency.sh and pg-cron.sh build it as probe-pg18-reliability:18.6 when it is missing.
FROM postgres:18.6-trixie
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    postgresql-18-cron=1.6.8-1.pgdg13+2 \
    pgbouncer=1.26.1-1.pgdg13+1 \
  && rm -rf /var/lib/apt/lists/*
