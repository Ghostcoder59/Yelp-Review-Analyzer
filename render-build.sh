#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Chromium + chromedriver (needed for Selenium on Render)
apt-get update -qq
apt-get install -y -qq chromium-browser chromium-chromedriver \
  || apt-get install -y -qq chromium chromium-driver \
  || echo "WARNING: Could not install chromium via apt — scraping will fail on server"

# Make sure requirements.txt is UTF-8 before pip reads it.
python - <<'PY'
from pathlib import Path

path = Path("requirements.txt")
raw = path.read_bytes()

try:
    raw.decode("utf-8")
except UnicodeDecodeError:
    path.write_text(raw.decode("utf-16"), encoding="utf-8")
    print("Converted requirements.txt to UTF-8")
PY

# Install Python dependencies
pip install gunicorn
pip install -r requirements.txt

# Download NLTK data
python -c "
import nltk
nltk.download('vader_lexicon')
nltk.download('stopwords')
nltk.download('wordnet')
"
