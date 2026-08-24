from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from html import unescape
import json

URL = "https://www.jeep-official.it/offerte-jeep-prezzi"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    soup = BeautifulSoup(page.content(), "html.parser")

    components = soup.find_all(attrs={"data-component": True})

    print("COMPONENTI PROMO/CPS:")
    for c in components:
        name = c.get("data-component")
        if name and ("promo" in name.lower() or "offer" in name.lower() or "cps" in name.lower()):
            print("-", name)

    component = soup.find(attrs={"data-component": "CPSAllPromotions"})

    if not component:
        print("CPSAllPromotions NON trovato")
        browser.close()
        raise SystemExit

    props = json.loads(unescape(component.get("data-props")))
    cards = props.get("cards", [])

    print("PROMO TROVATE:", len(cards))

    for i, card in enumerate(cards, start=1):
        cta = card.get("ctas") or {}
        print(i, card.get("headline"), "|", cta.get("href"))
        print("rate:", card.get("monthlyRate"))
        print("tan/taeg:", card.get("installment"))
        print("validita:", card.get("validityEndDate"))
        print("-" * 80)

    browser.close()
