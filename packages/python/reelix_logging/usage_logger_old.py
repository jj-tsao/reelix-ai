from datetime import datetime
from app.deps.deps import SupabaseCreds

import httpx


def log_query_and_results(
    query_entry: dict,
    result_entries: list[dict],
    creds: SupabaseCreds,
):
    if not creds.url or not creds.api_key:
        print("⚠️ Missing Supabase config, skipping log.")
        return

    timestamp = datetime.utcnow().isoformat()
    query_entry.setdefault("created_at", timestamp)
    for r in result_entries:
        r.setdefault("created_at", timestamp)

    headers = {
        "apikey": creds.api_key,
        "Authorization": f"Bearer {creds.api_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    try:
        query_resp = httpx.post(
            f"{creds.url}/rest/v1/query_logs",
            headers=headers,
            json=[query_entry]
        )

        if query_resp.status_code not in (200, 201, 204):
            print("⚠️ Failed to log usage:", query_resp.text)

        if result_entries:
            result_resp = httpx.post(
                f"{creds.url}/rest/v1/result_logs",
                headers=headers,
                json=result_entries
            )
            if result_resp.status_code not in (200, 201, 204):
                print("⚠️ Failed to log results:", result_resp.text)

    except Exception as e:
        print("❌ Logging error:", e)


def log_final_results(result_entries: list[dict], creds: SupabaseCreds):
    if not creds.url or not creds.api_key:
        print("⚠️ Missing Supabase config, skipping log.")
        return

    headers = {
        "apikey": creds.api_key,
        "Authorization": f"Bearer {creds.api_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    try:
        result_resp = httpx.post(
            f"{creds.url}/rest/v1/result_logs",
            headers=headers,
            json=result_entries
        )
        if result_resp.status_code not in (200, 201, 204):
            print("⚠️ Failed to log final results:", result_resp.text)
    except Exception as e:
        print("❌ Error in write_final_results:", e)

        

