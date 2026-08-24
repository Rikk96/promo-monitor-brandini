import re
from playwright.sync_api import sync_playwright

HUB = "https://drautomobiles.com/promo/"
OLD_URLS = [
    "https://drautomobiles.com/promozione-dr-5-collection-bz-gpl/",
    "https://drautomobiles.com/promozione-dr-5-full-hybrid-collection/",
    "https://drautomobiles.com/promozione-dr-6-collection/",
    "https://drautomobiles.com/promozione-dr-6-superhybrid-collection/",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 9000})

    print("===== 1) LINK TROVATI SULLA PAGINA HUB /promo/ =====")
    page.goto(HUB, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    links = page.eval_on_selector_all(
        "a[href*='drautomobiles.com/promozione']",
        "els => els.map(e => e.href)"
    )
    unique_links = sorted(set(links))
    for l in unique_links:
        marker = "GIA' IN LISTA" if l in OLD_URLS else "*** NUOVO / NON IN LISTA ***"
        print(f"  {l}   [{marker}]")
    print(f"\nTotale link unici trovati: {len(unique_links)}  |  In lista hardcoded: {len(OLD_URLS)}")

    print("\n===== 2) TEST REGEX SU CIASCUN URL HARDCODED =====")
    for url in OLD_URLS:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        has_bonus_dr = "Bonus DR" in body
        has_prezzo_listino = "Prezzo di listino" in body
        print(f"\n--- {url} ---")
        print(f"  Contiene 'Bonus DR': {has_bonus_dr} | Contiene 'Prezzo di listino': {has_prezzo_listino}")
        print(f"  Primi 500 caratteri body:\n  {body[:500]!r}")

    browser.close()
