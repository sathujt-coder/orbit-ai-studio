#!/bin/sh
# Validate mounted certificates/config before graceful edge reload.
# The operator must provision replacements from a trusted issuer first.
set -eu
cd "$(dirname "$0")"
docker compose -f compose.proxy.yml exec -T proxy nginx -t
docker compose -f compose.proxy.yml exec -T proxy nginx -s reload
# Native Python TLS context loads certificates at process start.
# If upstream TLS material changed, restart orbit separately and verify health.
