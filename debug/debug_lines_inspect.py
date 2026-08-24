from playwright.sync_api import sync_playwright

LINE_TARGETS = {
    "LEPAS (promo page)": "https://www.lepasautoitalia.com/promozioni/lepas-l8/",
    "DONGFENG (promo page)": "https://www.dongfeng-italia.it/promo/dongfeng-mage-phev-tua-da-eur-33900",
}

# Verifica se la pagina MODELLO (non /promo/) ha una nota legale più estesa
MODEL_PAGE_TARGETS = {
    "DONGFENG (model page /mage-phev)": "https://www.dongfeng-italia.it/mage-phev",
    "LEPAS (model page /modelli/lepas-l8)": "https://www.lepasautoitalia.com/modelli/lepas-l8/",
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 9000})

    print("\n\n########## PARTE 1: RIGHE INDICIZZATE (pagine /promo/) ##########")
    for name, url in LINE_TARGETS.items():
        print(f"\n{'='*20} {name} {'='*20}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        lines = body.split("\n")
        print(f"Totale righe: {len(lines)}")
        for i, l in enumerate(lines[:40]):
            print(f"[{i:3}] {l!r}")

    print("\n\n########## PARTE 2: PAGINE MODELLO (per capire se hanno TAN/TAEG completi) ##########")
    for name, url in MODEL_PAGE_TARGETS.items():
        print(f"\n{'='*20} {name} {'='*20}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as e:
            print(f"ERRORE caricamento: {e}")
            continue
        body = page.evaluate("() => document.body ? document.body.innerText : ''")
        has_tan = "TAN" in body or "Tan " in body
        has_taeg = "TAEG" in body or "Taeg" in body
        has_prezzo_promo = "promo" in body.lower() or "offerta" in body.lower()
        print(f"Lunghezza body: {len(body)} caratteri")
        print(f"Contiene 'TAN': {has_tan} | Contiene 'TAEG': {has_taeg} | Contiene 'promo/offerta': {has_prezzo_promo}")
        print(f"\n--- Primi 2000 caratteri ---")
        print(body[:2000])

    browser.close()
