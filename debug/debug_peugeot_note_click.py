from playwright.sync_api import sync_playwright
import re

URL="https://www.peugeot.it/acquista/offerte-privati/208.html"

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    page=browser.new_page(viewport={"width":1366,"height":1600})
    page.goto(URL,wait_until="networkidle",timeout=90000)
    page.wait_for_timeout(3000)

    before = page.locator("body").inner_text(timeout=30000)
    print("BEFORE LEN:", len(before))

    target = page.get_by_text("Nota legale e consumi", exact=False)
    print("COUNT:", target.count())

    if target.count() > 0:
        target.first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(1000)
        target.first.click(timeout=10000, force=True)
        page.wait_for_timeout(3000)

    after = page.locator("body").inner_text(timeout=30000)
    print("AFTER LEN:", len(after))

    for kw in ["Importo Totale", "Messaggio Pubblicitario", "Spese", "TAN", "TAEG", "Consumo", "Emissioni"]:
        print("\n==", kw, "==")
        idx=after.lower().find(kw.lower())
        print("IDX:", idx)
        if idx != -1:
            print(after[max(0,idx-800):idx+3000])

    browser.close()
