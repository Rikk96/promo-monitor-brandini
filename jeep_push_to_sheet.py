from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

from promo_common import HEADERS, with_retry
from jeep_to_sheet_v2 import build_rows, BRAND

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

rows = build_rows()
errors = []

for r in rows:
    r["Note Tecniche"] = r["Note Tecniche"].replace("debug_only_no_push", "").replace(";;", ";").strip("; ").strip()

print()
print("RIGHE JEEP:", len(rows))
print("ERRORI:", len(errors))
for e in errors:
    print("ERRORE:", e)

if errors:
    raise SystemExit("STOP: errori presenti, nessun push eseguito.")

if len(rows) < 6:
    raise SystemExit(f"STOP: attese almeno 6 righe Jeep, trovate {len(rows)}. Nessun push eseguito.")

creds = Credentials.from_service_account_file(KEY_PATH, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
gc = gspread.authorize(creds)
ws = with_retry(
    lambda: gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output"),
    label="apertura foglio jeep"
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

with_retry(lambda: ws.clear(), label="pulizia foglio jeep")
with_retry(lambda: ws.update("A1", values), label="scrittura foglio jeep")
ws.format("A:AA", {"wrapStrategy": "WRAP"})

print("PUSH COMPLETATO: righe Jeep scritte:", len(rows))
