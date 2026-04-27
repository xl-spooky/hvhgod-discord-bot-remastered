#!/bin/sh
set -eu

poetry install --no-root
exec ./scripts/migrate.sh "$@"
