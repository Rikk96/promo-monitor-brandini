from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

from promo_common import HEADERS, with_retry
from fiat_pro_to_sheet_v2 import build_rows, BRAND, MIN_EXPECTED_ROWS

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

rows = build_rows()
errors = []

print()
print("RIGHE FIAT PROFESSIONAL:", len(rows))

if len(rows) < MIN_EXPECTED_ROWS:
    raise SystemExit(f"STOP: attese almeno {MIN_EXPECTED_ROWS} righe Fiat Professional, trovate {len(rows)}. Nessun push eseguito.")

if len(rows) > MIN_EXPECTED_ROWS:
    print(f"ATTENZIONE: nuove offerte Fiat Professional trovate: {len(rows)} invece di baseline {MIN_EXPECTED_ROWS}. Push consentito.")

for i, r in enumerate(rows, start=1):
    is_leasys = "noleggio_leasys" in str(r.get("Note Tecniche",""))
    is_evolease = "leasing_finanziario" in str(r.get("Note Tecniche",""))

    required = ["Brand","Modello","Motorizzazione","Titolo Promo","Rata","Anticipo","Scadenza","Note Legali","Fonte URL","Offer URL"]
    for col in required:
        if not str(r.get(col,"")).strip():
            errors.append(f"{i} missing {col}: {r.get('Titolo Promo')}")

    if is_evolease:
        for col in ["Intero","TAN (%)","TAEG (%)"]:
            if not str(r.get(col,"")).strip():
                errors.append(f"{i} missing {col} evolease: {r.get('Titolo Promo')}")

    if is_leasys:
        if (
            str(r.get("TAN (%)","")).strip()
            or str(r.get("TAEG (%)","")).strip()
        ) and not is_evolease:
            errors.append(f"{i} Noleggio Leasys puro con TAN/TAEG valorizzati: {r.get('Titolo Promo')}")
        if "tan_taeg_not_applicable" not in str(r.get("Note Tecniche","")):
            errors.append(f"{i} missing tan_taeg_not_applicable: {r.get('Titolo Promo')}")

if errors:
    print("ERRORI:", len(errors))
    for e in errors:
        print("ERRORE:", e)
    raise SystemExit("STOP: errori presenti, nessun push eseguito.")

creds = Credentials.from_service_account_file(KEY_PATH, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
gc = gspread.authorize(creds)
ws = with_retry(
    lambda: gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output"),
    label="apertura foglio fiat_pro"
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

with_retry(lambda: ws.clear(), label="pulizia foglio fiat_pro")
with_retry(lambda: ws.update("A1", values), label="scrittura foglio fiat_pro")
ws.format("A:AA", {"wrapStrategy": "WRAP"})

print("PUSH COMPLETATO: righe Fiat Professional scritte:", len(rows))
