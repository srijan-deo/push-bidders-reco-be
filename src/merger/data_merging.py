import os
import pandas as pd
from datetime import datetime, timedelta
import pytz
from google.cloud import bigquery

def rename_tag_concat_and_pivot(one_to_one: pd.DataFrame) -> pd.DataFrame:

    # --- Step 1: Standardize column names ---
    df = one_to_one.copy()

    rename_map = {}
    if 'mbr_nbr' in df.columns:
        rename_map['mbr_nbr'] = 'input_buyer_nbr'
    if 'recommended_lot_nbr' in df.columns:
        rename_map['recommended_lot_nbr'] = 'recommended_lot'
    if 'lot_nbr' in df.columns and 'original_lot' not in df.columns:
        rename_map['lot_nbr'] = 'original_lot'

    df = df.rename(columns=rename_map)

    # --- Step 2: Keep only required columns ---
    required_cols = ['input_buyer_nbr', 'original_lot', 'recommended_lot']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    keep_cols = ['input_buyer_nbr', 'original_lot', 'recommended_lot']
    if 'cosine_similarity' in df.columns:
        keep_cols.append('cosine_similarity')

    df = df[keep_cols].dropna(subset=['input_buyer_nbr', 'original_lot', 'recommended_lot'])

    # --- Step 3: Ensure deterministic ordering ---
    if 'cosine_similarity' in df.columns:
        df = df.sort_values(
            ['input_buyer_nbr', 'original_lot', 'cosine_similarity'],
            ascending=[True, True, False]
        )
    else:
        df = df.sort_values(['input_buyer_nbr', 'original_lot'])

    # --- Step 4: Take only top 6 per buyer + original_lot ---
    df['rank'] = df.groupby(['input_buyer_nbr', 'original_lot']).cumcount() + 1
    df = df[df['rank'] <= 6]

    # --- Step 5: Pivot ---
    pivoted = df.pivot(
        index=['input_buyer_nbr', 'original_lot'],
        columns='rank',
        values='recommended_lot'
    ).reset_index()

    # --- Step 6: Rename columns to lot_1 ... lot_6 ---
    pivoted.columns = [
        f'lot_{int(col)}' if isinstance(col, int) else col
        for col in pivoted.columns
    ]

    # --- Step 7: Ensure all 6 lot columns exist ---
    lot_cols = [f'lot_{i}' for i in range(1, 7)]
    for col in lot_cols:
        if col not in pivoted.columns:
            pivoted[col] = 0

    pivoted = pivoted[['input_buyer_nbr', 'original_lot'] + lot_cols]

    # --- Step 8: Convert to int ---
    pivoted['input_buyer_nbr'] = pivoted['input_buyer_nbr'].astype(int)
    pivoted['original_lot'] = pivoted['original_lot'].astype(int)
    pivoted[lot_cols] = pivoted[lot_cols].fillna(0).astype(int)

    # --- Step 9: Add timestamps ---
    cst = pytz.timezone('US/Central')
    now_cst = datetime.now(cst)
    next_day_7am_cst = (now_cst + timedelta(days=1)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )

    pivoted['created_at'] = now_cst
    pivoted['sent_at'] = next_day_7am_cst

    return pivoted

# ==============================================================
# Save to Excel Helper (Always Excel)
# ==============================================================
def save_processed_data(df: pd.DataFrame):
    """
    Save the final merged recommendations file with tomorrow’s CST date.
    Output example: ../data/final/recommendations_2025-10-29.xlsx
    """

    # Get tomorrow’s date in CST (YYYY-MM-DD format)
    cst = pytz.timezone('US/Central')
    now_cst = datetime.now(cst)
    tomorrow_date = (now_cst + timedelta(days=1)).strftime("%Y-%m-%d")

    # Build file path (relative to root)
    file_path = f"data/final/recommendations_{tomorrow_date}.xlsx"

    # Ensure folder exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    for col in df.select_dtypes(include=['datetimetz']).columns:
        df[col] = df[col].dt.tz_localize(None)

    # Save DataFrame
    df.to_excel(file_path, index=False)

    print(f"✅ File saved successfully as: {file_path}")


# ==============================================================
# Upload merged recommendations to BigQuery
# ==============================================================
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



def main():
    final_pivoted_recos = rename_tag_concat_and_pivot(cf_test_reco, one_to_one_test_reco, nonactive_test_reco, cf_holdout_reco,
        one_to_one_holdout_reco, nonactive_holdout_reco, cf_holdout_would_have, one_to_one_holdout_would_have)

if __name__ == "__main__":
    cf_test_reco = pd.read_excel('../../data/results/cf_test_reco.xlsx')
    one_to_one_test_reco = pd.read_excel('../../data/results/onetoone_test_reco.xlsx')
    nonactive_test_reco = pd.read_excel('../../data/results/nonactive_test_reco.xlsx')

    cf_holdout_reco = pd.read_excel('../../data/results/cf_holdout_reco.xlsx')
    one_to_one_holdout_reco = pd.read_excel('../../data/results/onetoone_holdout_reco.xlsx')
    nonactive_holdout_reco = pd.read_excel('../../data/results/nonactive_holdout_reco.xlsx')

    cf_holdout_would_have = pd.read_excel('../../data/results/cf_holdout_would_have_reco.xlsx')
    one_to_one_holdout_would_have = pd.read_excel('../../data/results/onetoone_holdout_would_have_reco.xlsx')

    final_pivoted_recos = rename_tag_concat_and_pivot(cf_test_reco, one_to_one_test_reco, nonactive_test_reco, cf_holdout_reco,
                                one_to_one_holdout_reco, nonactive_holdout_reco, cf_holdout_would_have,
                                one_to_one_holdout_would_have)

    save_processed_data(final_pivoted_recos)

    upload_to_bigquery(
        dataframe=final_pivoted_recos,
        table_id="member_reco.test",
        project_id="cprtqa-strategicanalytics-sp1",
        credentials_path="/Users/srdeo/OneDrive - Copart, Inc/secrets/cprtqa-strategicanalytics-sp1-8b7a00c4fbae.json"
    )