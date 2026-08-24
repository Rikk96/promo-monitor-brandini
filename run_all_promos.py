import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS = [
    "fiat_push_to_sheet.py",
    "abarth_push_to_sheet.py",
    "lancia_push_to_sheet.py",
    "alfa_push_to_sheet.py",
    "jeep_push_to_sheet.py",
    "peugeot_push_to_sheet.py",
    "citroen_push_to_sheet.py",
    "opel_push_to_sheet.py",
    "ds_push_to_sheet.py",
    "fiat_pro_push_to_sheet.py",
    "nissan_push_to_sheet.py",
    "leapmotor_push_to_sheet.py",
    "honda_push_to_sheet.py",
    "mazda_push_to_sheet.py",
    "hyundai_push_to_sheet.py",
    "mg_push_to_sheet.py",
    "omodajaecoo_push_to_sheet.py",
    "changan_push_to_sheet.py",
    "bmw_push_to_sheet.py",
    "mini_push_to_sheet.py",
    "dr_push_to_sheet.py",
    "lepas_push_to_sheet.py",
    "dongfeng_push_to_sheet.py",
]

TIMEOUT_SECONDS = 10 * 60
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def ensure_service_account_key():
    key_path = Path("/tmp/key.json")

    if key_path.exists() and key_path.stat().st_size > 500:
        print("OK service account key già presente:", key_path)
        return

    print("Recupero service account key da Secret Manager...")

    try:
        from google.cloud import secretmanager

        project_id = "brandini-promo-monitor"
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/promo-monitor-sa-key/versions/latest"
        payload = client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")

        key_path.write_text(payload)
        key_path.chmod(0o600)

    except Exception as e:
        print("Secret Manager Python fallito, provo fallback gcloud:", e)
        cmd = [
            "gcloud", "secrets", "versions", "access", "latest",
            "--secret", "promo-monitor-sa-key",
            "--project", "brandini-promo-monitor",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise SystemExit("STOP: impossibile recuperare promo-monitor-sa-key")

        key_path.write_text(result.stdout)
        key_path.chmod(0o600)

    if not key_path.exists() or key_path.stat().st_size < 500:
        raise SystemExit("STOP: /tmp/key.json non valido")

    print("OK service account key pronta:", key_path)



run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
summary = []

print("=" * 100)
print(f"PROMO MONITOR RUN START | {run_id}")
print("=" * 100)

ensure_service_account_key()

for script in SCRIPTS:
    start = time.time()
    log_path = LOG_DIR / f"{run_id}_{script.replace('.py', '')}.log"

    print()
    print("-" * 100)
    print(f"START {script}")
    print("-" * 100)

    if not Path(script).exists():
        msg = f"FILE MANCANTE: {script}"
        print(msg)
        summary.append((script, "MISSING", 0, msg))
        continue

    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )

        elapsed = round(time.time() - start, 1)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        log_path.write_text(output)

        if result.returncode == 0:
            status = "OK"
            print(f"OK {script} | {elapsed}s | log={log_path}")
        else:
            status = "FAIL"
            print(f"FAIL {script} | code={result.returncode} | {elapsed}s | log={log_path}")
            print("=" * 100)
            print(f"OUTPUT COMPLETO FAIL | {script}")
            print("=" * 100)
            print(output[-20000:])
            print("=" * 100)

        summary.append((script, status, elapsed, str(log_path)))

    except subprocess.TimeoutExpired as e:
        elapsed = round(time.time() - start, 1)
        output = (e.stdout or "") + "\n" + (e.stderr or "")
        log_path.write_text(output)
        print(f"TIMEOUT {script} | {elapsed}s | log={log_path}")
        summary.append((script, "TIMEOUT", elapsed, str(log_path)))

print()
print("=" * 100)
print("PROMO MONITOR RUN SUMMARY")
print("=" * 100)

ok = 0
bad = 0

for script, status, elapsed, info in summary:
    print(f"{status:8} | {elapsed:>6}s | {script} | {info}")
    if status == "OK":
        ok += 1
    else:
        bad += 1

print()
print(f"TOTAL OK: {ok}")
print(f"TOTAL BAD: {bad}")
print(f"RUN ID: {run_id}")

if bad:
    raise SystemExit(1)

print("RUN COMPLETATO SENZA ERRORI")
