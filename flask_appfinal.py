import flask
from flask import Flask, request, jsonify, render_template
import pickle
import numpy as np
import scipy.sparse as sp
import re
import time
import pandas as pd
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- NLTK setup ---
for resource in [('sentiment/vader_lexicon.zip', 'vader_lexicon'),
                 ('corpora/stopwords', 'stopwords'),
                 ('corpora/wordnet', 'wordnet')]:
    try:
        nltk.data.find(resource[0])
    except LookupError:
        nltk.download(resource[1], quiet=True)

# --- Load models ---
try:
    vectorizer = pickle.load(open("tfidf_vectorizer.pkl", "rb"))
    model = pickle.load(open("isolation_forest_yelp.pkl", "rb"))
    print("Models loaded successfully.")
except Exception as e:
    print(f"Error loading models: {e}")


def create_driver():
    """
    Exact same driver setup as live_yelp_analysis.ipynb.
    On Render (Linux): runs headless with system chromium.
    On Windows/Mac (local): runs visibly — no headless, avoids Yelp bot detection.
    """
    import platform
    import os
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    chrome_options = Options()
    is_linux = platform.system() == "Linux"

    if is_linux:
        # Render server — no display, must use headless
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        for binary in ["/usr/bin/chromium-browser", "/usr/bin/chromium"]:
            if os.path.exists(binary):
                chrome_options.binary_location = binary
                break
    else:
        # Windows / Mac — NO headless (same as notebook, avoids bot detection)
        chrome_options.add_argument("--start-maximized")

    # Anti-detection flags (identical to notebook)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    if is_linux:
        # Render native runtime may not have system Chrome installed.
        # Try system chromedriver first, then Selenium Manager auto-provision,
        # then webdriver-manager as a final fallback.
        driver = None
        linux_binaries = [
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ]

        found_binary = next((b for b in linux_binaries if os.path.exists(b)), None)
        if found_binary:
            chrome_options.binary_location = found_binary

        try:
            if os.path.exists("/usr/bin/chromedriver"):
                driver = webdriver.Chrome(
                    service=Service("/usr/bin/chromedriver"),
                    options=chrome_options,
                )
            else:
                # Selenium Manager path: can auto-manage driver/browser.
                driver = webdriver.Chrome(options=chrome_options)
        except Exception:
            try:
                driver = webdriver.Chrome(options=chrome_options)
            except Exception:
                from webdriver_manager.chrome import ChromeDriverManager

                driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=chrome_options,
                )
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )

    # Remove selenium fingerprint (identical to notebook)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def build_yelp_page_url(url, start_offset):
    parts = urlsplit(url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))

    if start_offset:
        query_params["start"] = str(start_offset)
    else:
        query_params.pop("start", None)

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_params, doseq=True), parts.fragment))


def fetch_yelp_reviews(url, page_count=1):
    """
    Exact same scraping logic as live_yelp_analysis.ipynb.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    page_count = max(1, int(page_count or 1))
    driver = create_driver()
    reviews = []
    seen_reviews = set()

    try:
        for page_index in range(page_count):
            page_url = build_yelp_page_url(url, page_index * 10)
            try:
                driver.get(page_url)

                wait = WebDriverWait(driver, 20)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "p")))
            except TimeoutException:
                break

            for _ in range(5):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

            elements = driver.find_elements(By.TAG_NAME, "p")
            if not elements:
                break

            for el in elements:
                text = el.text.strip()
                if len(text) > 80 and text not in seen_reviews:
                    seen_reviews.add(text)
                    reviews.append(text)
    finally:
        driver.quit()

    return reviews


def explain_anomaly(review_text, decision_score, sentiment_score):
    reasons = []
    word_count = len(review_text.split())
    if word_count < 10:
        reasons.append("Unusually short review length, a common trait of bot-generated spam.")
    elif word_count > 300:
        reasons.append("Unusually long review length compared to typical bounds.")
    if sentiment_score > 0.9:
        reasons.append(
            f"Extreme positive polarization (Score: {sentiment_score:.2f}). "
            "Fake reviews are often wildly exaggerated."
        )
    elif sentiment_score < -0.9:
        reasons.append(
            f"Extreme negative polarization (Score: {sentiment_score:.2f}). "
            "Fake reviews often show heavy exaggeration."
        )
    upper_chars = sum(1 for c in review_text if c.isupper())
    if len(review_text) > 0 and (upper_chars / len(review_text)) > 0.2:
        reasons.append("Excessive use of capital letters (>20%), common in promotional/spam content.")
    if review_text.count('!') > 4:
        reasons.append("Excessive use of exclamation marks detected.")
    if not reasons:
        reasons.append("Subtle statistical mismatch in terminology or structural density against normal baseline.")
    return reasons


def get_sentiment(text):
    sid = SentimentIntensityAnalyzer()
    return sid.polarity_scores(text)['compound']


def preprocess_reviews(raw_reviews):
    from nltk.corpus import stopwords
    from nltk.stem import WordNetLemmatizer

    stop_words = set(stopwords.words('english'))
    lemmatizer = WordNetLemmatizer()

    clean_docs = []
    for review in raw_reviews:
        text = review.lower()
        text = re.sub(r"http\S+", "", text)
        text = re.sub(r"[^a-z\s]", "", text)
        tokens = text.split()
        cleaned_tokens = [lemmatizer.lemmatize(word) for word in tokens if word not in stop_words]
        clean_docs.append(" ".join(cleaned_tokens))

    return clean_docs


def score_reviews(raw_reviews):
    clean_docs = preprocess_reviews(raw_reviews)

    # --- Features (must match training) ---
    X_text = vectorizer.transform(clean_docs)
    review_lengths = sp.csr_matrix([[len(review.split())] for review in clean_docs])
    rating_placeholders = sp.csr_matrix([[3] for _ in clean_docs])
    X_live = sp.hstack([X_text, review_lengths, rating_placeholders])

    # --- Predict ---
    predictions = model.predict(X_live)
    d_scores = model.decision_function(X_live)

    suspicious_count = 0
    results = []
    for review, pred, d_score in zip(raw_reviews, predictions, d_scores):
        sentiment_score = get_sentiment(review)
        is_fake = bool(pred == -1)
        if is_fake:
            suspicious_count += 1
        reasons = explain_anomaly(review, d_score, sentiment_score) if is_fake else []
        results.append({
            "text": review,
            "is_fake": is_fake,
            "sentiment_score": float(sentiment_score),
            "anomaly_score": float(d_score),
            "reasons": reasons
        })

    susp_percentage = (suspicious_count / len(results)) * 100 if results else 0
    return results, susp_percentage


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/api/analyze/url', methods=['POST'])
def analyze_url():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    page_count = data.get("pages", 1)

    if "yelp.com" not in url.lower():
        return jsonify({"error": "Invalid Yelp URL"}), 400

    try:
        page_count = int(page_count)
        if page_count < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Page count must be a positive integer"}), 400

    try:
        raw_reviews = fetch_yelp_reviews(url, page_count=page_count)
    except Exception as e:
        return jsonify({"error": f"Scraping failed: {str(e)}"}), 500

    if not raw_reviews:
        return jsonify({"error": "No reviews extracted. Yelp may have blocked the request."}), 404

    results, susp_percentage = score_reviews(raw_reviews)

    return jsonify({
        "total_reviews": len(results),
        "suspicious_percentage": susp_percentage,
        "reviews": results
    })


@app.route('/api/insights', methods=['GET'])
def get_insights():
    try:
        df = pd.read_csv("yelp_reviews_clean.csv")
        avg_rating = float(df['rating'].mean())
        avg_words = float(df['review_length'].mean())
        rating_counts = df['rating'].value_counts().sort_index().to_dict()

        return jsonify({
            "total_reviews": len(df),
            "average_rating": avg_rating,
            "average_word_count": avg_words,
            "rating_distribution": {str(k): int(v) for k, v in rating_counts.items()}
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
