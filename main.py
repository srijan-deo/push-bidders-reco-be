import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import time
import pandas as pd
from src.data.data_ingestion import ingest_dataset, get_bq_client
from src.data.data_preprocessing import preprocess_all
from src.model.one_to_one import refine_recommendations_parallel_per_buyer_fast, save_processed_data as save_one_to_one_data
#from memory_profiler import profile
from google.cloud import bigquery
from collections import defaultdict
import time

from src.bid_eligible.auth_token import get_access_token
from src.bid_eligible.bid_eligibility import run_bid_eligibility

def log_time(step_name, start_time):
    duration = time.time() - start_time
    minutes = duration // 60
    seconds = duration % 60
    print(f"⏱️ {step_name} completed in {int(minutes)}m {seconds:.2f}s\n")


def main():
    print("🚀 Starting full recommendation pipeline...\n")
    overall_start = time.time()

    #───────────────────────────────────────────────────────────────
    step = "STEP 1️⃣: BigQuery Ingestion"
    print(f"\n{step}")
    start = time.time()
    #cred_path = "/Users/srdeo/Documents/Recommendations/cprtpr-datastewards-sp1-614d7e297848 (1).json"
    cred_path = "/Users/srdeo/Documents/secrets/stewardapp-prbq-key 1.json"
    client = get_bq_client(cred_path)

    tasks = [
        ("Active Buyers", "src/queries/active_buyers.sql", "data/raw/active_buyers.csv"),
        ("Upcoming Lots", "src/queries/upcoming_lots.sql", "data/raw/upcoming_lots.csv"),
        ("Lids Data Past", "src/queries/lids_past.sql", "data/raw/lids_past.csv"),
        ("Lids Data Future", "src/queries/lids_future.sql", "data/raw/lids_future.csv"),
        ("Bid Eligibility", "src/queries/bid_eligibility.sql", "data/raw/be_logic.csv")
    ]
    for name, query_path, output_path in tasks:
        print(f"Ingesting: {name}")
        #ingest_dataset(client, query_path, output_path)
    log_time(step, start)

    # ───────────────────────────────────────────────────────────────
    step = "STEP 2️⃣: Preprocessing"
    print(f"\n{step}")
    start = time.time()
    active = pd.read_csv("data/raw/active_buyers.csv")
    upcoming = pd.read_csv("data/raw/upcoming_lots.csv")
    lids_past = pd.read_csv("data/raw/lids_past.csv")
    lids_future = pd.read_csv("data/raw/lids_future.csv")
    active_clean, upcoming_clean = preprocess_all(active, upcoming, lids_past, lids_future)
    log_time(step, start)

   # ───────────────────────────────────────────────────────────────
    step = "STEP 5️⃣: One-to-One Refinement"
    print(f"\n{step}")
    start = time.time()

    be_logic = pd.read_csv("data/raw/be_logic.csv")
   
    push_bidders_reco = refine_recommendations_parallel_per_buyer_fast(active_clean, upcoming_clean, be_logic)
    #save_one_to_one_data(push_bidders_reco, "data/results/push_bidders_reco.xlsx")
    log_time(step, start)
   
   # # ───────────────────────────────────────────────────────────────
    step = "STEP 5️⃣: Access Token"
    print(f"\n{step}")
    start = time.time()

    access_token = get_access_token()

    log_time(step, start)
   # # ───────────────────────────────────────────────────────────────
    step = "STEP 7: Bid eligiblity"

    push_bidders_reco_be = run_bid_eligibility(
        df=push_bidders_reco,
        access_token=access_token,
        buyer_col="input_buyer_nbr",
        lot_col="recommended_lot"
    )

    push_bidders_reco_be.to_excel("data/final/push_bidders_reco_be_reco.xlsx", index=False)
    print("🏁 ALL STEPS COMPLETED")
    log_time("TOTAL PIPELINE", overall_start)

if __name__ == "__main__":
    main()