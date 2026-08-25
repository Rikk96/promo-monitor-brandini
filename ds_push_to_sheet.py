from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, with_retry
from ds_to_sheet_v2 import get_urls, parse_detail, BRAND


def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

run_id = "ds_push_" + datetime.now().strftime("%Y%m%d_%H%M%S")
rows = []
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    hub = browser.new_page(viewport={"width":1366,"height":7000})
    urls = get_urls(hub)
    print("URL DS TROVATI:", len(urls))

    detail = browser.new_page(viewport={"width":1366,"height":10000})

    for i, url in enumerate(urls, start=1):
        r = parse_detail(detail, url, run_id)
        if not r:
            errors.append(f"{i} NO_ROW {url}")
            continue

        r["Note Tecniche"] = r["Note Tecniche"].replace("debug_only_no_push", "").replace(";;", ";").strip("; ").strip()
        rows.append(r)

        print(f"{i}/{len(urls)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | {r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | {r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']} | {r['Note Tecniche']}")

        required = ["Brand","Modello","Motorizzazione","Titolo Promo","Rata","Intero","TAN (%)","TAEG (%)","Scadenza","Note Legali","Anticipo","Importo Totale Credito","Importo Totale Dovuto"]
        for col in required:
            if not str(r.get(col,"")).strip():
                errors.append(f"{r['Modello']} | {r['Titolo Promo']} | missing {col}")

        if r.get("Legal Source Status") != "extended_legal_found":
            errors.append(f"{r['Modello']} | {r['Titolo Promo']} | legal status {r.get('Legal Source Status')}")

    browser.close()

print("\nRIGHE DS:", len(rows))
print("ERRORI:", len(errors))
for e in errors:
    print("ERRORE:", e)

if errors:
    raise SystemExit("STOP: anomalie presenti, nessun push eseguito.")

creds = Credentials.from_service_account_file(KEY_PATH, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])

gc = gspread.authorize(creds)
ws = with_retry(
    lambda: gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output"),
    label="apertura foglio ds"
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

with_retry(lambda: ws.clear(), label="pulizia foglio ds")
with_retry(lambda: ws.update("A1", values), label="scrittura foglio ds")
ws.freeze(rows=1)
ws.format("1:1", {"textFormat": {"bold": True}})
ws.format("A:AA", {"verticalAlignment": "TOP", "wrapStrategy": "WRAP"})

print("PUSH COMPLETATO: righe DS scritte:", len(rows))
