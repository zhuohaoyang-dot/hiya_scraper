#!/bin/bash
set -e

echo "=== Starting Hiya Scraper API ==="
echo "Python version:"
python --version

echo "Current directory:"
pwd

echo "Files in directory:"
ls -la

echo "Testing imports..."
python -c "import flask; print('✓ Flask OK')"
python -c "import flask_cors; print('✓ Flask-CORS OK')"
python -c "import playwright; print('✓ Playwright OK')"
python -c "from playwright.async_api import async_playwright; print('✓ Playwright async OK')"

echo "Testing scraper import..."
python -c "from scraper import HiyaScraper; print('✓ Scraper OK')"

echo "Testing API import..."
python -c "from api import app; print('✓ API OK')"

echo "All imports successful! Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --threads 2 --log-level debug --access-logfile - --error-logfile - api:app
