from playwright.sync_api import sync_playwright

URLS = [
    "https://drautomobiles.com/promozione-dr-5-stilnovo/",
    "https://drautomobiles.com/promozione-dr-6-stilnovo/",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 9000})
    for url in URLS:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        print(f"\n===== {url} =====")
        # Stampa dal titolo modello fino a fine nota legale (primi 1200 char utili)
        idx = body.find("Modelli")
        print(body[idx:idx+1400] if idx >= 0 else body[:1400])
    browser.close()
