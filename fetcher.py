import hashlib
import logging
import random
import re
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────
BLOG_URL = "https://metamuseum.tumblr.com"
SAVE_DIR = Path("images")
DB_FILE = "fetcher.db"

MAX_PAGES = 50
DELAY_MIN = 2.0
DELAY_MAX = 4.0
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


# ── DB SETUP ───────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fetch_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT,
        url TEXT,
        status INTEGER,
        success INTEGER,
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS images (
        hash TEXT PRIMARY KEY,
        url TEXT,
        saved_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS state (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    return conn


def log_fetch(conn, url, status, success, note=""):
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO fetch_log (ts, url, status, success, note) VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            url,
            status,
            int(success),
            note,
        ),
    )

    conn.commit()


def get_state(conn, key, default=0):
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM state WHERE key=?",
        (key,)
    )

    row = cur.fetchone()

    return int(row[0]) if row else default


def set_state(conn, key, value):
    cur = conn.cursor()

    cur.execute(
        "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
        (key, str(value)),
    )

    conn.commit()


# ── Safe GET ───────────────────────────────────────
def safe_get(session, conn, url):
    for attempt in range(1, MAX_RETRIES + 1):

        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=15,
                impersonate="chrome120",
            )

            log_fetch(
                conn,
                url,
                r.status_code,
                r.status_code == 200,
                f"attempt {attempt}"
            )

            if r.status_code == 200 and len(r.content) > 200:
                return r

        except Exception as e:
            log_fetch(conn, url, None, False, str(e))

        time.sleep(2 * attempt + random.uniform(0.5, 1.5))

    log.error(f"[FAILED] {url}")

    return None


# ── Helpers ────────────────────────────────────────
def hash_content(content):
    return hashlib.sha256(content).hexdigest()


def _upgrade_resolution(url: str) -> str:
    return re.sub(r"/s\d+x\d+/", "/s2048x3072/", url)


def extract_image_urls(html):
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


# ── Download ───────────────────────────────────────
def download_image(session, conn, url):
    r = safe_get(session, conn, url)

    if not r:
        return False

    h = hash_content(r.content)

    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM images WHERE hash=?",
        (h,)
    )

    if cur.fetchone():
        return False

    ext = url.split(".")[-1].split("?")[0]

    path = SAVE_DIR / f"{h}.{ext}"

    path.write_bytes(r.content)

    cur.execute(
        "INSERT INTO images (hash, url, saved_at) VALUES (?, ?, ?)",
        (
            h,
            url,
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()

    log.info(f"[SAVED] {h[:10]}")

    return True


# ── MAIN ───────────────────────────────────────────
def main():
    SAVE_DIR.mkdir(exist_ok=True)

    conn = init_db()

    session = requests.Session()

    start_page = get_state(conn, "last_page", 0) + 1

    for page in range(start_page, start_page + 1):

        url = f"{BLOG_URL}/page/{page}"

        log.info(f"\n── Page {page} ──────────────────────")

        r = safe_get(session, conn, url)

        if not r:
            break

        image_urls = extract_image_urls(r.text)

        log.info(f"Found {len(image_urls)} image URLs")

        if not image_urls:
            log.info("Empty page → stopping")
            break

        new_count = 0

        for img_url in image_urls:

            time.sleep(
                DELAY_MIN + random.uniform(0, DELAY_MAX - DELAY_MIN)
            )

            if download_image(session, conn, img_url):
                new_count += 1

        log.info(f"New images this page: {new_count}")

        # ✅ KEY FIX: stop if nothing new
        if new_count == 0:
            log.info("No new images → stopping crawl")
            break

        set_state(conn, "last_page", page)

    log.info("\nDone.")


if __name__ == "__main__":
    main()