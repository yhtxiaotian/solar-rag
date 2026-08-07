#!/bin/sh
set -eu

mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  pg_dump --format=custom --file="/backups/database-${stamp}.dump"
  tar -czf "/backups/knowledge-${stamp}.tar.gz" -C /knowledge .
  find /backups -type f -mtime +7 -delete
  sleep 86400
done

