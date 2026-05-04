"""
metamuseum_scraper.py
"""

import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from curl_cffi import requests  # replaces standard requests
from bs4 import BeautifulSoup

# ── Config ───────────────────────────────────────────────────────────────────
BLOG_URL    = "https://metamuseum.tumblr.com"
SAVE_DIR    = Path("images")
LOG_FILE    = Path("fetch_log.jsonl")
STATE_FILE  = Path("state.json")
MAX_PAGES   = 50
DELAY_MIN   = 2.0
DELAY_MAX   = 4.0
MAX_RETRIES = 3

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.tumblr.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Structured fetch log (JSONL) ─────────────────────────────────────────────
def log_fetch(url: str, status: Optional[int], success: bool, note: str = ""):
    record = {
        "ts":      datetime.now(timezone.utc).isoformat(),
        "url":     url,
        "status":  status,
        "success": success,
        "note":    note,
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ── State persistence ─────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_page": 0, "seen_hashes": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Safe GET (curl_cffi impersonates Chrome at TLS level) ────────────────────
def safe_get(session, url: str, params: dict = None):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=15,
                impersonate="chrome120",   # <-- bypasses Cloudflare TLS fingerprint
            )
            log_fetch(url, r.status_code, r.status_code == 200, f"attempt {attempt}")

            if r.status_code == 200 and len(r.content) > 200:
                return r

            if r.status_code == 404:
                log.info("404 – end of blog.")
                return None

            log.warning(f"[HTTP {r.status_code}] attempt {attempt}/{MAX_RETRIES}")

        except Exception as e:
            log_fetch(url, None, False, f"exception: {e}")
            log.warning(f"[ERR] attempt {attempt}/{MAX_RETRIES} – {e}")

        if attempt < MAX_RETRIES:
            time.sleep(2 * attempt + random.uniform(0.5, 1.5))

    log.error(f"[FAILED] {url}")
    return None


# ── Resolution upgrade ────────────────────────────────────────────────────────
def _upgrade_resolution(url: str) -> str:
    return re.sub(r"/s\d+x\d+/", "/s2048x3072/", url)


# ── Extract image URLs from HTML ─────────────────────────────────────────────
def extract_image_urls(html: str) -> set:
    soup = BeautifulSoup(html, "html.parser")
    urls = set()

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "media.tumblr.com" in src:
            urls.add(_upgrade_resolution(src))

    for img in soup.find_all("img", srcset=True):
        for part in img["srcset"].split(","):
            candidate = part.strip().split(" ")[0]
            if "media.tumblr.com" in candidate:
                urls.add(_upgrade_resolution(candidate))

    return urls


# ── Download with deduplication ───────────────────────────────────────────────
def download_image(session, url: str, seen_hashes: set) -> Optional[str]:
    r = safe_get(session, url)
    if not r:
        return None

    h = hashlib.sha256(r.content).hexdigest()

    if h in seen_hashes:
        log.info(f"[SKIP] duplicate {h[:12]}...")
        return None

    ext = url.split(".")[-1].split("?")[0].lower()
    ext = ext if ext in ("jpg", "jpeg", "png", "gif", "webp") else "jpg"

    path = SAVE_DIR / f"{h}.{ext}"
    if path.exists():
        seen_hashes.add(h)
        return None

    path.write_bytes(r.content)
    seen_hashes.add(h)
    log.info(f"[SAVED] {h[:12]}....{ext}  ({len(r.content) // 1024} KB)")
    return h


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    SAVE_DIR.mkdir(exist_ok=True)

    state = load_state()
    seen_hashes = set(state["seen_hashes"])
    start_page = state["last_page"] + 1

    # curl_cffi session — no headers in constructor, passed per-request
    session = requests.Session()

    max_p = MAX_PAGES if MAX_PAGES is not None else 9999

    for page_num in range(start_page, max_p + 1):
        url = f"{BLOG_URL}/page/{page_num}"
        log.info(f"\n── Page {page_num} ──────────────────────")

        r = safe_get(session, url)
        if not r:
            log.info("Stopping.")
            break

        image_urls = extract_image_urls(r.text)
        log.info(f"Found {len(image_urls)} image URLs")

        if not image_urls:
            log.info("Empty page – reached the end.")
            break

        for img_url in image_urls:
            time.sleep(DELAY_MIN + random.uniform(0, DELAY_MAX - DELAY_MIN))
            download_image(session, img_url, seen_hashes)

        state["last_page"] = page_num
        state["seen_hashes"] = list(seen_hashes)
        save_state(state)

        time.sleep(DELAY_MIN + random.uniform(0, 1.0))

    log.info(f"\nDone. {len(seen_hashes)} unique images total.")


if __name__ == "__main__":
    main()