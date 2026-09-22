#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE USER airflow WITH PASSWORD '$AIRFLOW_DB_PASSWORD';
CREATE DATABASE airflow_db OWNER airflow;
EOSQL
