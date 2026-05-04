import requests
from bs4 import BeautifulSoup
import os

URL = "https://metamuseum.tumblr.com/page/1"

SAVE_DIR = "images"
os.makedirs(SAVE_DIR, exist_ok=True)


def download_image(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=15)

        if response.status_code != 200:
            print(f"[FAIL] {url}")
            return

        filename = url.split("/")[-1]
        path = os.path.join(SAVE_DIR, filename)

        with open(path, "wb") as f:
            f.write(response.content)

        print(f"[SAVED] {filename}")

    except Exception as e:
        print(f"[ERROR] {url} -> {e}")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def extract_image_urls(html):
    soup = BeautifulSoup(html, "html.parser")
    image_urls = set()

    for img in soup.find_all("img"):
        src = img.get("src")

        if src and "media.tumblr.com" in src:
            image_urls.add(src)

    return image_urls


def main():
    session = requests.Session()

    response = session.get(URL, headers=HEADERS, timeout=10)

    print("Status Code:", response.status_code)

    html = response.text

    images = extract_image_urls(html)

    print(f"\nFound {len(images)} images:\n")

    for url in list(images)[:10]:  # print first 10
        print(url)

    for url in images:
        download_image(session, url)


if __name__ == "__main__":
    main()