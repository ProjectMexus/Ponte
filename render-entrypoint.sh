#!/bin/bash
set -e

# Create database directory
mkdir -p /app/database

# Start nginx in foreground (daemon off)
nginx -g "daemon off;" &

# Start mock backend
python -m mock_backends.server --host 127.0.0.1 --port 8080 --data-dir /app/database &

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..30}; do
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/mock/medical/v1/departments', timeout=2)" 2>/dev/null; then
        echo "Backend ready"
        break
    fi
    sleep 1
done

# Start middleware (foreground, blocks)
exec python -m middleware.server --host 127.0.0.1 --port 8090
