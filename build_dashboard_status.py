import ast
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNNER = BASE_DIR / "run_all_promos.py"
SYSTEM_LOG = BASE_DIR / "logs" / "systemd.log"
OUTPUT = BASE_DIR / "dashboard" / "status.json"

SUMMARY_LINE = re.compile(
    r"^(OK|FAIL|TIMEOUT|MISSING)\s+\|\s*([\d.]+)s\s+\|\s+"
    r"([^|]+?)\s+\|\s+(.+)$"
)

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|authorization|password|secret)"
    r"(\s*[:=]\s*)(\S+)"
)


def configured_scripts():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "SCRIPTS":
                return ast.literal_eval(node.value)

    raise RuntimeError("Variabile SCRIPTS non trovata")


def safe_excerpt(log_path, limit=8000):
    if not log_path.exists():
        return "Log non disponibile"

    text = log_path.read_text(encoding="utf-8", errors="replace")
    text = SECRET_PATTERN.sub(r"\1\2[REDACTED]", text)
    return text[-limit:].strip()


def latest_summary():
    text = SYSTEM_LOG.read_text(encoding="utf-8", errors="replace")
    marker = "PROMO MONITOR RUN SUMMARY"
    start = text.rfind(marker)

    if start < 0:
        raise RuntimeError("Nessun riepilogo trovato in systemd.log")

    section = text[start:]
    run_match = re.search(r"^RUN ID:\s*(\d{8}_\d{6})\s*$", section, re.M)

    if not run_match:
        raise RuntimeError("RUN ID non trovato nell'ultimo riepilogo")

    run_id = run_match.group(1)
    results = {}

    for line in section[:run_match.end()].splitlines():
        match = SUMMARY_LINE.match(line.strip())
        if not match:
            continue

        status, elapsed, script, info = match.groups()
        results[script.strip()] = {
            "status": status,
            "elapsed_seconds": float(elapsed),
            "info": info.strip(),
        }

    return run_id, results


def brand_name(script):
    special = {
        "alfa": "Alfa Romeo",
        "fiat_pro": "Fiat Professional",
        "omodajaecoo": "Omoda / Jaecoo",
        "ds": "DS",
        "dr": "DR",
        "mg": "MG",
        "bmw": "BMW",
        "mini": "MINI",
    }

    key = script.replace("_push_to_sheet.py", "")
    return special.get(key, key.replace("_", " ").title())


def main():
    scripts = configured_scripts()
    run_id, results = latest_summary()
    run_time = datetime.strptime(run_id, "%Y%m%d_%H%M%S").astimezone()

    items = []

    for script in scripts:
        result = results.get(script)

        if result is None:
            items.append({
                "brand": brand_name(script),
                "script": script,
                "status": "NOT_RUN",
                "elapsed_seconds": 0,
                "log_excerpt": "",
            })
            continue

        info = result["info"]
        log_path = Path(info)

        if not log_path.is_absolute():
            log_path = BASE_DIR / log_path

        excerpt = ""
        if result["status"] != "OK":
            excerpt = safe_excerpt(log_path)

        items.append({
            "brand": brand_name(script),
            "script": script,
            "status": result["status"],
            "elapsed_seconds": result["elapsed_seconds"],
            "log_excerpt": excerpt,
        })

    ok = sum(item["status"] == "OK" for item in items)
    bad = sum(item["status"] in {"FAIL", "TIMEOUT", "MISSING"} for item in items)
    not_run = sum(item["status"] == "NOT_RUN" for item in items)

    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "run_type": "scheduled",
        "run_started_at": run_time.isoformat(timespec="seconds"),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall_status": "OK" if bad == 0 and not_run == 0 else "ERROR",
        "totals": {
            "configured": len(scripts),
            "ok": ok,
            "bad": bad,
            "not_run": not_run,
        },
        "items": items,
    }

    OUTPUT.parent.mkdir(exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(OUTPUT)

    print(f"Creato: {OUTPUT}")
    print(f"Run: {run_id}")
    print(f"Configurati: {len(scripts)} | OK: {ok} | BAD: {bad} | NOT_RUN: {not_run}")


if __name__ == "__main__":
    main()
