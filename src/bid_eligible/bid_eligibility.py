import time
import threading
import requests
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from google.cloud import bigquery
from zoneinfo import ZoneInfo

# PATCH: added imports needed for the pooled/retrying session (HTTPAdapter + urllib3 Retry)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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


# PATCH: new helper — builds one shared Session with a connection pool sized to max_workers
# and automatic retry/backoff for transient errors (429/500/502/503/504) at the transport
# level. This replaces per-call requests.get() (which opened/closed a fresh connection each
# time) with warm, reused connections — this is what was causing SSLEOFError under load.
def make_session(pool_size=20):
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# PATCH: safe_check now takes a `session` param instead of using the module-level
# requests.get(). Also split the generic except block into a specific branch for
# SSLError/ConnectionError vs everything else, so connection-level failures are
# visible and handled distinctly rather than silently retried the same way as any
# other exception.
def safe_check(session, buyer, lot, access_token):
    url = f"{API_BASE}?lotNumber={lot}&buyerNumber={buyer}&language=en"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "country": "USA"
    }

    for attempt in range(6):
        try:
            rate_limiter.wait()

            r = session.get(url, headers=headers, timeout=20)

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

        # PATCH: SSLError/ConnectionError now caught separately from generic Exception,
        # since these indicate a broken connection (e.g. the SSLEOFError seen in prod)
        # rather than an application-level issue — logged distinctly so it's easy to
        # spot in logs, still retries via the loop.
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            print(f"Connection/SSL error for buyer={buyer}, lot={lot} (attempt {attempt + 1}/6): {e}")
            time.sleep(1)

        except Exception as e:
            print(f"Exception for buyer={buyer}, lot={lot}: {e}")
            time.sleep(1)

    return False


# PATCH: process_row now accepts and passes through the shared session.
def process_row(session, idx, row, access_token):
    buyer = row["input_buyer_nbr"]
    lot = row["recommended_lot"]

    result = safe_check(session, buyer, lot, access_token)

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

    # PATCH: one shared session for the whole run, pool sized to max_workers so every
    # worker thread gets a warm, reusable connection instead of opening a fresh one
    # per request.
    session = make_session(pool_size=max_workers)

    # PATCH: rows are now submitted to the executor in bounded batches instead of all
    # at once. The original code built a dict comprehension over every row in df up
    # front — for a large df (hundreds of thousands of buyer-lot pairs) this created
    # every row copy (.rename()), every closure, and every queued Future in memory
    # simultaneously before any work had even started, which is what caused the OOM
    # kill. Batching caps how much is in flight at any one time.
    rows = list(df.iterrows())
    batch_size = max_workers * 5

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for start in tqdm(range(0, len(rows), batch_size), desc="Batches"):
            batch = rows[start:start + batch_size]

            futures = {
                executor.submit(
                    process_row,
                    session,
                    idx,
                    row.rename({
                        buyer_col: "input_buyer_nbr",
                        lot_col: "recommended_lot"
                    }),
                    access_token
                ): idx
                for idx, row in batch
            }

            for future in as_completed(futures):
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
