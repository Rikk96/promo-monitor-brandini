from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
from html import unescape

URL = "https://www.fiat.it/offerte-privati"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    soup = BeautifulSoup(page.content(), "html.parser")

    component = soup.find(attrs={"data-component": "CPSAllPromotions"})

    if not component:
        print("Componente CPSAllPromotions NON trovato")
        browser.close()
        raise SystemExit

    raw_props = component.get("data-props")
    props = json.loads(unescape(raw_props))

    cards = props.get("cards", [])

    print("Promo trovate:", len(cards))
    print()

    for i, card in enumerate(cards, start=1):
        cta = card.get("ctas") or {}
        print(i)
        print("headline:", card.get("headline"))
        print("href:", cta.get("href"))
        print("shortAbstract:", card.get("shortAbstract"))
        print("monthlyRate:", card.get("monthlyRate"))
        print("installment:", card.get("installment"))
        print("validityEndDate:", card.get("validityEndDate"))
        print("-" * 80)

    browser.close()
