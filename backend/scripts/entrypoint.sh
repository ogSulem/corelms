#!/usr/bin/env sh
set -e

export PYTHONPATH=/app

exec python -m app.launcher api
