#!/usr/bin/env bash
# exit on error
set -o errexit

# Attempt to install Chromium + chromedriver when system package install is available.
# Render native Python builds may not allow apt operations (read-only filesystem).
if command -v apt-get >/dev/null 2>&1 && [ -d "/var/lib/apt/lists" ]; then
  if apt-get update -qq >/dev/null 2>&1; then
    apt-get install -y -qq chromium-browser chromium-chromedriver >/dev/null 2>&1 \
      || apt-get install -y -qq chromium chromium-driver >/dev/null 2>&1 \
      || echo "WARNING: Could not install chromium via apt. URL scraping may fail on server."
  else
    echo "WARNING: apt-get is present but not writable in this build environment. Skipping OS package install."
  fi
else
  echo "WARNING: apt-get not available. Skipping OS package install."
fi

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
