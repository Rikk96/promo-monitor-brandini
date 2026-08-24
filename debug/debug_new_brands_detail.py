from playwright.sync_api import sync_playwright

URLS = {
    "LEPAS L8 (dettaglio)": "https://www.lepasautoitalia.com/promozioni/lepas-l8/",
    "DONGFENG Mage PHEV (dettaglio)": "https://www.dongfeng-italia.it/promo/dongfeng-mage-phev-tua-da-eur-33900",
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 9000})

    for name, url in URLS.items():
        print(f"\n{'='*20} {name} {'='*20}")
        print(f"URL: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as e:
            print(f"ERRORE: {e}")
            continue

        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        print(f"\n--- BODY COMPLETO ({len(body)} caratteri) ---")
        print(body)

    browser.close()
