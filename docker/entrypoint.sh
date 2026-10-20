#!/bin/sh
# Brings the schema up to date, then runs the given command (default: mailspider serve).
# The importer runs the same way: docker compose run --rm backend mailspider import
set -e

if [ "${MAILSPIDER_AUTO_MIGRATE:-1}" = "1" ]; then
    mailspider migrate
fi

exec "$@"
