from playwright.sync_api import sync_playwright
import re

URL = "https://www.opel.it/offerte/privati/corsa-finanziamento.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 1600})

    page.goto(URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3000)

    # clicca esattamente l'accordion
    acc = page.get_by_text("Nota legale e consumi", exact=False)
    print("accordion count:", acc.count())

    if acc.count() > 0:
        acc.first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(1000)
        acc.first.click(timeout=10000, force=True)
        page.wait_for_timeout(2000)

    text = page.locator("body").inner_text(timeout=30000)

    # cerco il blocco giusto
    start = text.lower().find("dettaglio promozione")
    print("start:", start)

    if start == -1:
        print("NON TROVATO DETTAGLIO PROMOZIONE")
        print(text[:3000])
    else:
        # taglio prima di footer/cookie
        sub = text[start:]

        stops = [
            "Configura",
            "Contatta il Concessionario",
            "Pronta consegna",
            "CONTINUA SENZA ACCETTARE",
            "LA TUA PRIVACY",
            "Chatta con noi"
        ]

        end = len(sub)
        for s in stops:
            idx = sub.find(s)
            if idx != -1:
                end = min(end, idx)

        legal = sub[:end].strip()

        print("\n=== LEGAL ESTRATTA ===\n")
        print(legal)

    browser.close()
