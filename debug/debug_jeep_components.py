from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL = "https://www.jeep-official.it/offerte-jeep-prezzi"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    print("TITLE:", page.title())
    print("URL:", page.url)
    print("HTML LENGTH:", len(html))

    print("\nDATA-COMPONENT:")
    comps = sorted(set([c.get("data-component") for c in soup.find_all(attrs={"data-component": True}) if c.get("data-component")]))
    for c in comps:
        print("-", c)

    print("\nCERCA TERMINI:")
    for term in ["promo", "offert", "TAN", "TAEG", "rata", "validità", "data-props", "cards"]:
        idx = html.lower().find(term.lower())
        print(term, "=>", idx)
        if idx != -1:
            print(html[max(0, idx-500):idx+1000])
            print("-" * 80)

    browser.close()
