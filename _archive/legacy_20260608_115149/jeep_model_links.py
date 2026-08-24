from playwright.sync_api import sync_playwright

URL = "https://www.jeep-official.it/offerte-jeep-prezzi"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
    page = browser.new_page()

    page.goto(URL, wait_until="networkidle", timeout=90000)

    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text:(a.innerText||'').trim(),
            href:a.href
        }))
    """)

    for l in links:
        txt = (l["text"] or "").upper()

        if any(x in txt for x in [
            "AVENGER",
            "COMPASS",
            "CHEROKEE"
        ]):
            print(txt)
            print(l["href"])
            print("-"*80)

    browser.close()
