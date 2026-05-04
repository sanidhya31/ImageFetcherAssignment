import requests
from bs4 import BeautifulSoup

URL = "https://metamuseum.tumblr.com/page/1"

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


if __name__ == "__main__":
    main()