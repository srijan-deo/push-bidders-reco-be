import time
import threading
import requests
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from google.cloud import bigquery
from zoneinfo import ZoneInfo

API_BASE = "https://c-bideligibility-ws.copart.com/v1/ineligibility-reason-for-dynamic-lot-details"


class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.interval = 1.0 / rate_per_sec
        self.lock = threading.Lock()
        self.next_allowed_time = time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()

            if now < self.next_allowed_time:
                time.sleep(self.next_allowed_time - now)
                now = time.monotonic()

            self.next_allowed_time = now + self.interval


rate_limiter = RateLimiter(rate_per_sec=10)


def safe_check(buyer, lot, access_token):
    url = f"{API_BASE}?lotNumber={lot}&buyerNumber={buyer}&language=en"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "country": "USA"
    }

    for attempt in range(6):
        try:
            rate_limiter.wait()

            r = requests.get(url, headers=headers, timeout=20)

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    print(f"JSON parse failed for buyer={buyer}, lot={lot}: {r.text}")
                    return False

                if "memberEligible" in data:
                    return bool(data["memberEligible"])

                print(f"Lot unavailable or invalid for buyer={buyer}, lot={lot}: {data}")
                return False

            if r.status_code == 429:
                print(f"429 for buyer={buyer}, lot={lot} -> waiting 2 sec")
                time.sleep(2)
                continue

            if r.status_code == 401:
                print(f"401 TOKEN EXPIRED / INVALID for buyer={buyer}, lot={lot}")
                return False

            if r.status_code == 404:
                print(f"404 LOT NOT FOUND for buyer={buyer}, lot={lot}")
                return False

            print(f"Unexpected status {r.status_code} for buyer={buyer}, lot={lot}: {r.text}")
            time.sleep(1)

        except Exception as e:
            print(f"Exception for buyer={buyer}, lot={lot}: {e}")
            time.sleep(1)

    return False


def process_row(idx, row, access_token):
    buyer = row["input_buyer_nbr"]
    lot = row["recommended_lot"]

    result = safe_check(buyer, lot, access_token)

    return idx, True if result is True else False


def run_bid_eligibility(
    df,
    access_token,
    buyer_col="input_buyer_nbr",
    lot_col="recommended_lot",
    output_col="Bid_Eligibility",
    max_workers=20
):
    df = df.copy()

    required_cols = [buyer_col, lot_col]
    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    df[output_col] = False

    print("Running bid eligibility check with max 10 requests/sec...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_row,
                idx,
                row.rename({
                    buyer_col: "input_buyer_nbr",
                    lot_col: "recommended_lot"
                }),
                access_token
            ): idx
            for idx, row in df.iterrows()
        }

        for future in tqdm(as_completed(futures), total=len(futures)):
            idx, result = future.result()
            df.at[idx, output_col] = result

    print("DONE!")

    df["created_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).date()

    return df

def upload_to_bigquery(dataframe, table_id, project_id, client):
    print(f"\n📤 Uploading data to BigQuery table `{table_id}`...")

    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
        autodetect=True,
    )

    job = client.load_table_from_dataframe(
        dataframe,
        destination=f"{project_id}.{table_id}",
        job_config=job_config,
    )

    job.result()  # wait

    print(f"✅ Data successfully appended to `{table_id}` in `{project_id}`")
