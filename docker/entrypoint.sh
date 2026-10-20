#!/bin/sh
# Brings the schema up to date, then runs the given command (default: mailrobbe serve).
# The importer runs the same way: docker compose run --rm backend mailrobbe import
set -e

if [ "${MAILROBBE_AUTO_MIGRATE:-1}" = "1" ]; then
    mailrobbe migrate
fi

exec "$@"
