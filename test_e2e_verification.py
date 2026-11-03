import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8000"

def get(path):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode('utf-8')

def post(path, data):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read().decode('utf-8')

print("=== STARTING FULL END-TO-END WORKBENCH VERIFICATION ===")

# 1. Test Static files
status, html = get("/")
assert status == 200, f"GET / failed: {status}"
assert "Rate Change Assurance" in html
print("✓ GET / returned 200 OK with Rate Change Assurance views")

status, app_js = get("/static/js/app.js")
assert status == 200
assert "app.init()" in app_js
print("✓ GET /static/js/app.js returned 200 OK")

status, wb_js = get("/static/js/rate_change_workbench.js")
assert status == 200
assert "rateChangeWorkbench.init()" in wb_js
print("✓ GET /static/js/rate_change_workbench.js returned 200 OK")

# 2. Test Health
status, health_raw = get("/api/v1/health")
assert status == 200
print(f"✓ Health check: {health_raw.strip()}")

# 3. Test Sample Manuals
status, manuals_raw = get("/api/v1/rating-manuals/samples")
assert status == 200
manuals = json.loads(manuals_raw)
old_manual = manuals["old_manual"]
new_manual = manuals["new_manual"]
print(f"✓ Sample manuals: Old='{old_manual['manual_id']}' (v{old_manual['version']}), New='{new_manual['manual_id']}' (v{new_manual['version']})")

# 4. Test Sample Census
status, census_raw = get("/api/v1/rate-change/sample-census")
assert status == 200
census = json.loads(census_raw)
print(f"✓ Sample census: {len(census)} policies retrieved")

# 5. Test Rating Manual Comparison
status, comp_raw = post("/api/v1/rating-manuals/compare", {
    "old_manual": old_manual,
    "new_manual": new_manual
})
assert status == 200
comp = json.loads(comp_raw)
print("Manual comparison keys:", list(comp.keys()))

# 6. Test Portfolio Reconciliation
status, recon_raw = post("/api/v1/rate-change/reconcile-portfolio", {
    "old_manual": old_manual,
    "new_manual": new_manual,
    "census": census
})
assert status == 200
recon = json.loads(recon_raw)
print(f"✓ Portfolio reconciliation:")
print(f"   Old Premium: ${recon['total_old_premium']:.2f}")
print(f"   New Premium: ${recon['total_new_premium']:.2f}")
print(f"   Aggregate Dollar Change: ${recon['aggregate_dollar_change']:.2f} ({recon['aggregate_percentage_change']:.2f}%)")
print(f"   Reconciliation Residual: ${recon['aggregate_reconciliation_residual']:.6f}")
print(f"   Zero Residual Guaranteed: {recon['is_aggregate_reconciled']}")
assert recon['is_aggregate_reconciled'] is True
assert abs(recon['aggregate_reconciliation_residual']) < 1e-6

# 7. Test Dual Verification
status, verif_raw = post("/api/v1/verification/verify-census", {
    "manual": new_manual,
    "census": census
})
assert status == 200
verif = json.loads(verif_raw)
print(f"✓ Dual independent verification:")
print(f"   Total policies checked: {verif['total_policies_checked']}")
print(f"   Exact matches: {verif['total_passed']}")
print(f"   100% Verified: {verif['is_100_percent_verified']}")
print(f"   Max intermediate discrepancy: {verif['max_intermediate_discrepancy']:.2e}")
assert verif['is_100_percent_verified'] is True

# 8. Test Audit Ledger Status
status, ledger_raw = get("/api/v1/rate-change/audit-ledger/status")
assert status == 200
ledger = json.loads(ledger_raw)
print(f"✓ Audit ledger status:")
print(f"   Total records: {ledger['total_records']}")
print(f"   Chain valid: {ledger['is_valid']}")
print(f"   Tamper detected: {ledger['tamper_detected']}")
assert ledger['is_valid'] is True
assert ledger['tamper_detected'] is False

# 9. Test Report Generation (Markdown)
status, md_raw = post("/api/v1/rate-change/generate-report", {
    "old_manual": old_manual,
    "new_manual": new_manual,
    "census": census,
    "output_format": "markdown",
    "record_in_ledger": True
})
assert status == 200
md_resp = json.loads(md_raw)
assert "Rate Change Assurance" in md_resp["report"]
record_idx = md_resp.get("audit_trail", {}).get("record_index", "N/A")
print(f"✓ Report Generation (Markdown): Success, {len(md_resp['report'])} chars, ledger record #{record_idx}")

# 10. Test Report Generation (HTML)
status, html_raw = post("/api/v1/rate-change/generate-report", {
    "old_manual": old_manual,
    "new_manual": new_manual,
    "census": census,
    "output_format": "html",
    "record_in_ledger": True
})
assert status == 200
html_resp = json.loads(html_raw)
assert "<!DOCTYPE html>" in html_resp["report"]
record_idx_html = html_resp.get("audit_trail", {}).get("record_index", "N/A")
print(f"✓ Report Generation (HTML): Success, {len(html_resp['report'])} chars, ledger record #{record_idx_html}")

print("\n=== ALL 10 END-TO-END VERIFICATION CHECKS PASSED PERFECTLY ===")
