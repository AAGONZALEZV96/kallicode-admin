#!/usr/bin/env sh 
python -m admin_workers.main &
python -m http.server $PORT