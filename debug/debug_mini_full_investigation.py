from playwright.sync_api import sync_playwright

URL = "https://www.mini.it/it_IT/home/range/all-electric-mini-aceman/offers.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 10000})

    print("===== STEP 1: caricamento pagina, body COMPLETO (non troncato) =====")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    body1 = page.evaluate("() => document.body.innerText")
    print(f"Lunghezza: {len(body1)} caratteri")
    print(body1)

    print("\n\n===== STEP 2: cerco bottoni/link cliccabili con testo 'offerta', 'scopri', 'dettagli', 'condizioni' =====")
    clickable = page.eval_on_selector_all(
        "a, button",
        "els => els.map(e => e.innerText.trim()).filter(t => t.length > 0 && t.length < 60)"
    )
    relevant = [c for c in clickable if any(k in c.lower() for k in ["offert", "scopri", "dettagli", "condizion", "leasing", "finanz"])]
    print("Elementi cliccabili rilevanti trovati:")
    for r in sorted(set(relevant)):
        print(" -", r)

    print("\n\n===== STEP 3: provo a cliccare 'Scopri le offerte' o simile e rileggo il body =====")
    try:
        btn = page.locator("text=/scopri.*offert/i").first
        if btn.count() > 0:
            btn.click(timeout=5000)
            page.wait_for_timeout(3000)
            body2 = page.evaluate("() => document.body.innerText")
            print(f"Lunghezza DOPO click: {len(body2)} caratteri")
            if len(body2) > len(body1):
                print("CAMBIATO! Nuovo contenuto:")
                print(body2[len(body1):len(body1)+2000] if len(body2) > len(body1) else "nessuna differenza")
            else:
                print("Nessun cambiamento rilevante dopo il click")
        else:
            print("Nessun bottone 'scopri offerte' trovato da cliccare")
    except Exception as e:
        print(f"Click fallito o non necessario: {e}")

    browser.close()
