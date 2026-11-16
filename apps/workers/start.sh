#!/usr/bin/env sh 
set -e
python -m admin_workers.main &
exec python -m http.server ${PORT:-8000}
