import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

URL = "https://www.fiat.it/offerte-privati"

headers = {
    "User-Agent": "Mozilla/5.0"
}

resp = requests.get(URL, headers=headers, timeout=30)

print("STATUS:", resp.status_code)
print("HTML LENGTH:", len(resp.text))

soup = BeautifulSoup(resp.text, "lxml")

links = []

for a in soup.find_all("a", href=True):
    href = a["href"]

    full_url = urljoin(URL, href)

    if (
        "offerte" in full_url.lower()
        or "promo" in full_url.lower()
        or "privati" in full_url.lower()
    ):
        links.append(full_url)

links = sorted(list(set(links)))

print("\nLINK TROVATI:\n")

for link in links:
    print(link)
