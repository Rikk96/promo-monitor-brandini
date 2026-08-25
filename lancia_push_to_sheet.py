from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, with_retry
from lancia_to_sheet_v2 import get_urls, parse_detail, BRAND

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

run_id = "lancia_push_" + datetime.now().strftime("%Y%m%d_%H%M%S")
rows = []
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

    hub = browser.new_page(viewport={"width":1366,"height":8000})
    urls = get_urls(hub)

    print("URL LANCIA TROVATI:", len(urls))

    detail = browser.new_page(viewport={"width":1366,"height":10000})

    for i, url in enumerate(urls, start=1):
        try:
            r = parse_detail(detail, url, run_id)

            if not r:
                errors.append(f"{i}/{len(urls)} NO_ROW {url}")
                print(f"{i}/{len(urls)} | NO_ROW | {url}")
                continue

            r["Note Tecniche"] = r["Note Tecniche"].replace("debug_only_no_push", "").replace(";;", ";").strip("; ").strip()

            rows.append(r)

            print(
                f"{i}/{len(urls)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                f"{r['Rata']} | {r['Intero']} | {r['Anticipo']} | {r['Rata Finale / VFG']} | "
                f"{r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | "
                f"{r['Legal Source Status']} | {r['Note Tecniche']}"
            )

        except Exception as e:
            err = f"{i}/{len(urls)} ERR {url} | {e}"
            errors.append(err)
            print("ERRORE:", err)

    browser.close()

print()
print("RIGHE LANCIA:", len(rows))
print("ERRORI:", len(errors))
for e in errors:
    print("ERRORE:", e)

if errors:
    raise SystemExit("STOP: errori presenti, nessun push eseguito.")

if len(rows) != 10:
    raise SystemExit(f"STOP: attese 10 righe Lancia, trovate {len(rows)}. Nessun push eseguito.")

creds = Credentials.from_service_account_file(KEY_PATH, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
gc = gspread.authorize(creds)
ws = with_retry(
    lambda: gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output"),
    label="apertura foglio lancia"
)

existing = ws.get_all_records()
kept = [r for r in existing if str(r.get("Brand","")).strip().lower() != BRAND.lower()]
final_rows = kept + rows

values = [HEADERS] + [[safe_cell_value(r.get(h, "")) for h in HEADERS] for r in final_rows]

too_long = []
for ri, row in enumerate(values, start=1):
    for ci, cell in enumerate(row, start=1):
        if len(str(cell)) > 50000:
            too_long.append((ri, ci, len(str(cell))))

if too_long:
    raise SystemExit(f"STOP: celle oltre 50k prima del clear: {too_long[:10]}")

with_retry(lambda: ws.clear(), label="pulizia foglio lancia")
with_retry(lambda: ws.update("A1", values), label="scrittura foglio lancia")
ws.format("A:AA", {"wrapStrategy": "WRAP"})

print("PUSH COMPLETATO: righe Lancia scritte:", len(rows))
