from playwright.sync_api import sync_playwright
import re

URL = "https://www.jeep-official.it/jeep-avenger/benzina"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1600})

    page.goto(URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(5000)

    text = page.locator("body").inner_text(timeout=30000)

    print("TITLE:", page.title())
    print("URL:", page.url)
    print("TEXT LENGTH:", len(text))

    for kw in [
        "TAN",
        "TAEG",
        "rata",
        "rate",
        "€",
        "Offerta valida",
        "fino al",
        "Validità",
        "Messaggio Pubblicitario",
        "Dettaglio promozione"
    ]:
        print("\n==========", kw, "==========")
        matches = [m.start() for m in re.finditer(kw, text, re.I)]
        print("MATCH:", len(matches))

        for idx in matches[:3]:
            print(text[max(0, idx-700):idx+1500])
            print("-"*100)

    browser.close()
