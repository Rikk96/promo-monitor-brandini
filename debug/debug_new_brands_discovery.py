from playwright.sync_api import sync_playwright

TARGETS = {
    "LEPAS": "https://www.lepasautoitalia.com/promozioni/",
    "DONGFENG": "https://www.dongfeng-italia.it/promo",
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 9000})

    for name, url in TARGETS.items():
        print(f"\n{'='*20} {name}: {url} {'='*20}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as e:
            print(f"ERRORE nel caricamento: {e}")
            continue

        # 1) Tutti i link della pagina che sembrano puntare a offerte/modelli
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href)"
        )
        base_domain = url.split('/')[2]
        relevant = sorted(set(
            l for l in links
            if base_domain in l and l != url and not any(
                x in l.lower() for x in ["privacy", "cookie", "javascript:", "#", "mailto:", "tel:"]
            )
        ))
        print(f"\n--- Link interni rilevanti trovati: {len(relevant)} ---")
        for l in relevant[:40]:
            print(" ", l)
        if len(relevant) > 40:
            print(f"  ... e altri {len(relevant)-40}")

        # 2) Testo grezzo della pagina hub (per capire se le offerte sono già tutte qui)
        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        print(f"\n--- Primi 1500 caratteri del body (per capire se e' single_page) ---")
        print(body[:1500])

    browser.close()
