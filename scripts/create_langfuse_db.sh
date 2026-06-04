#!/usr/bin/env bash
# Runs inside the Postgres image on first boot (empty pgdata volume).
# The official postgres entrypoint executes every *.sh and *.sql in
# /docker-entrypoint-initdb.d/ in alphabetical order.
#
# Creates the `langfuse` database used by the self-hosted Langfuse
# observability service (Wave 1.5 of the DD uplift). A separate database
# inside the same Postgres instance — no extra container, just a logical
# isolation boundary.
#
# CREATE DATABASE IF NOT EXISTS doesn't exist in Postgres, so we query
# pg_database manually. Connecting to the default `postgres` maintenance
# DB because CREATE DATABASE cannot run inside the target DB itself.

set -euo pipefail

existing=$(psql --username "$POSTGRES_USER" --dbname postgres \
  --tuples-only --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname = 'langfuse'")

if [[ -z "$existing" ]]; then
  psql --username "$POSTGRES_USER" --dbname postgres \
    --command "CREATE DATABASE langfuse OWNER \"$POSTGRES_USER\";"
  echo "Created database 'langfuse' (owner: $POSTGRES_USER) for self-hosted Langfuse."
else
  echo "Database 'langfuse' already exists, skipping."
fi
