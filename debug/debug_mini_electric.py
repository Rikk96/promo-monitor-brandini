from playwright.sync_api import sync_playwright

URLS = {
    "MINI Aceman": "https://www.mini.it/it_IT/home/range/all-electric-mini-aceman/offers.html",
    "MINI Cooper Elettrica": "https://www.mini.it/it_IT/home/range/all-electric-mini-cooper/offers.html",
    "MINI Countryman Elettrica": "https://www.mini.it/it_IT/home/range/all-electric-mini-countryman/offers.html",
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 10000})

    for name, url in URLS.items():
        print(f"\n{'='*20} {name} {'='*20}")
        print(f"URL: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        body = page.evaluate("() => document.body.innerText")
        print(f"Lunghezza body: {len(body)} caratteri")
        has_esempio = "Un esempio rappresentativo" in body
        has_note_legali = "Note legali" in body
        print(f"Contiene 'Un esempio rappresentativo': {has_esempio} | Contiene 'Note legali': {has_note_legali}")
        print(f"\n--- Primi 1500 caratteri ---")
        print(body[:1500])

    browser.close()
