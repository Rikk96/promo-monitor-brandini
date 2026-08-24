from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL = "https://www.jeep-official.it/offerte-jeep-prezzi"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    soup = BeautifulSoup(page.content(), "html.parser")

    elems = soup.find_all(attrs={"data-props": True})

    print("ELEMENTI CON DATA-PROPS:", len(elems))

    for i, e in enumerate(elems[:50], start=1):
        print("\n---", i)

        print("tag:", e.name)

        if e.get("data-component"):
            print("component:", e.get("data-component"))

        if e.get("data-app-wl"):
            print("app:", e.get("data-app-wl"))

        props = e.get("data-props","")

        print(props[:500])
        print("="*80)

    browser.close()
