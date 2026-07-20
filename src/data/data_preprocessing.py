import os
import pandas as pd
from packaging.version import parse
# ==============================================================
# Fill Missing grp_model (Hierarchical Logic)
# ==============================================================

def _fill_grp_model_year_make(group: pd.DataFrame) -> pd.DataFrame:
    """Helper: fill grp_model within (lot_year, lot_make_cd)."""
    mode_val = group['grp_model'].mode()
    if not mode_val.empty:
        group['grp_model'] = group['grp_model'].fillna(mode_val[0])
    return group

def _fill_grp_model_make(group: pd.DataFrame) -> pd.DataFrame:
    """Helper: fill grp_model within lot_make_cd."""
    mode_val = group['grp_model'].mode()
    if not mode_val.empty:
        group['grp_model'] = group['grp_model'].fillna(mode_val[0])
    return group

def fill_missing_grp_model(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill missing 'grp_model' using hierarchical mode logic:
    1. Within (lot_year, lot_make_cd)
    2. Within (lot_make_cd)
    3. Drop remaining rows where grp_model is still NaN
    """
    df = df.groupby(['lot_year', 'lot_make_cd'], group_keys=False).apply(_fill_grp_model_year_make)
    df = df.reset_index(drop=True)  # FIX: avoid 'lot_make_cd' being both an index level and a column label
    df = df.groupby(['lot_make_cd'], group_keys=False).apply(_fill_grp_model_make)
    df = df.reset_index(drop=True)  # FIX: keep index clean for any downstream groupby/merge
    df = df.dropna(subset=['grp_model'])
    return df




# ==============================================================
# Clean Active buyers
# ==============================================================
def clean_active_buyers(df: pd.DataFrame) -> pd.DataFrame:

    # PATCH: guarded against empty .mode() (was: df['mbr_lic_type'].fillna(df['mbr_lic_type'].mode()[0])) to avoid KeyError: 0 when column is all-NaN
    mode_val = df['mbr_lic_type'].mode()
    if not mode_val.empty:
        df['mbr_lic_type'] = df['mbr_lic_type'].fillna(mode_val.iloc[0])

    # PATCH: guarded against empty .mode() (was: df['mbr_state'].fillna(df['mbr_state'].mode()[0])) to avoid KeyError: 0 when column is all-NaN
    mode_val = df['mbr_state'].mode()
    if not mode_val.empty:
        df['mbr_state'] = df['mbr_state'].fillna(mode_val.iloc[0])

    df['mbr_lic_type'] = df['mbr_lic_type'].replace('Automotive Related Business', 'General Business')

    df = df.groupby(['lot_year', 'lot_make_cd'], group_keys=False).apply(_fill_grp_model_year_make)
    df = df.reset_index(drop=True)  # FIX: avoid 'lot_make_cd' being both an index level and a column label
    df = df.groupby(['lot_make_cd'], group_keys=False).apply(_fill_grp_model_make)
    df = df.reset_index(drop=True)  # FIX: keep index clean for any downstream groupby/merge
    df = df.dropna(subset=['grp_model'])

    df.loc[df['lot_title'].str.upper().str.strip() == 'NON-REPAIRABLE', 'lot_title'] = 'SALVAGE TITLE'

    df['acv'] = df['acv'].mask(df['acv']<=0, df['plug_lot_acv'])
    df['acv'] = (df['acv'] - df['acv'].min()) / (df['acv'].max() - df['acv'].min() + 1e-8)

    df['repair_cost'] = (df['repair_cost'] - df['repair_cost'].min()) / (df['repair_cost'].max() - df['repair_cost'].min() + 1e-8)

    df_top6 = (df.sort_values(['buyer_nbr', 'bid_dttm'], ascending=[True, False]).groupby('buyer_nbr', as_index=False).head(6).reset_index(drop=True))
    
    return df_top6

# ==============================================================
# Clean Non Active buyers
# ==============================================================
def clean_non_active_buyers(df: pd.DataFrame) -> pd.DataFrame:

    # PATCH: guarded against empty .mode() (was: df['mbr_lic_type'].fillna(df['mbr_lic_type'].mode()[0])) to avoid KeyError: 0 when column is all-NaN
    mode_val = df['mbr_lic_type'].mode()
    if not mode_val.empty:
        df['mbr_lic_type'] = df['mbr_lic_type'].fillna(mode_val.iloc[0])

    # PATCH: guarded against empty .mode() (was: df['mbr_state'].fillna(df['mbr_state'].mode()[0])) to avoid KeyError: 0 when column is all-NaN
    mode_val = df['mbr_state'].mode()
    if not mode_val.empty:
        df['mbr_state'] = df['mbr_state'].fillna(mode_val.iloc[0])

    df['mbr_lic_type'] = df['mbr_lic_type'].replace('Automotive Related Business', 'General Business')
    df = df.rename(columns={'mbr_lic_type': 'buyer_type'})

    return df

# ==============================================================
# 3️⃣ Clean Popular Lots
# ==============================================================

def clean_popular_lots(popular_df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans and ranks popular lots data with fallback.
    """

    # 0. Work on a copy
    popular_df = popular_df.copy()

    # 1. Basic cleaning
    popular_df['buyer_type'] = popular_df['buyer_type'].replace(
        'Automotive Related Business', 'General Business'
    )

    mode_val = popular_df['buyer_type'].mode()
    if not mode_val.empty:
        popular_df['buyer_type'] = popular_df['buyer_type'].fillna(mode_val[0])

    popular_df = popular_df.groupby('grp_model', group_keys=False).apply(
        _fill_grp_model_make
    )
    popular_df = popular_df.reset_index(drop=True)  # FIX: avoid 'grp_model' being both an index level and a column label

    popular_df['median_acv'] = popular_df['median_acv'].mask(
        popular_df['median_acv'] <= 0,
        popular_df['median_plug_lot_acv']
    )

    global_pool = (
        popular_df
        .sort_values(['buyer_type', 'cnt'], ascending=[True, False])
        .drop_duplicates(['buyer_type', 'lot_make_cd', 'grp_model'])
        .copy()
    )

    state_df = (
        popular_df
        .sort_values(['buyer_type', 'mbr_state', 'cnt'], ascending=[True, True, False])
        .drop_duplicates(['buyer_type', 'mbr_state', 'lot_make_cd', 'grp_model'])
        .copy()
    )

    final_rows = []

    for (bt, st), group in state_df.groupby(['buyer_type', 'mbr_state']):
        group = group.copy()
        group['source_scope'] = 'STATE'

        need = 6 - len(group)
        if need > 0:
            fb = global_pool[global_pool['buyer_type'] == bt].copy()
            fb = fb[
                ~fb.set_index(['lot_make_cd', 'grp_model']).index.isin(
                    group.set_index(['lot_make_cd', 'grp_model']).index
                )
            ]
            fb = fb.head(need)

            if not fb.empty:
                fb['mbr_state'] = st
                fb['source_scope'] = 'GLOBAL_FALLBACK'
                group = pd.concat([group, fb], ignore_index=True)

        group = group.sort_values('cnt', ascending=False)
        group['rank_clean'] = range(1, len(group) + 1)
        group = group[group['rank_clean'] <= 6]

        final_rows.append(group)

    return pd.concat(final_rows, ignore_index=True)


# ==============================================================
# 4️⃣ Clean Upcoming lots
# ==============================================================

def clean_upcoming_lots(df: pd.DataFrame) -> pd.DataFrame:

    mode_val = df['damage_type_desc'].mode()
    if not mode_val.empty:
        df['damage_type_desc'] = df['damage_type_desc'].fillna(mode_val[0])

    df = df.groupby(['lot_year', 'lot_make_cd'], group_keys=False).apply(_fill_grp_model_year_make)
    df = df.reset_index(drop=True)  # FIX: avoid 'lot_make_cd' being both an index level and a column label
    df = df.groupby(['lot_make_cd'], group_keys=False).apply(_fill_grp_model_make)
    df = df.reset_index(drop=True)  # FIX: keep index clean for any downstream groupby/merge
    df = df.dropna(subset=['grp_model'])

    df.loc[df['lot_title'].str.upper().str.strip() == 'NON-REPAIRABLE', 'lot_title'] = 'SALVAGE TITLE'

    df['acv'] = df['acv'].mask(df['acv']<=0, df['plug_lot_acv'])
    df['acv'] = (df['acv'] - df['acv'].min()) / (df['acv'].max() - df['acv'].min() + 1e-8)

    df['repair_cost'] = (df['repair_cost'] - df['repair_cost'].min()) / (df['repair_cost'].max() - df['repair_cost'].min() + 1e-8)


    return df

# ==============================================================
# 4️⃣ Clean Lids Data
# ==============================================================

def clean_lids_data(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if 'damage' in col.lower() or 'detected' in col.lower():
            df[col] = df[col].fillna(1)

    df['lids_version'] = df['lids_version'].str.strip('"')
    mode_val = df['lids_version'].mode()

    if not mode_val.empty:
        df['lids_version'] = df['lids_version'].fillna(mode_val.iloc[0])

    # Step 3: Parse versions for proper sorting
    df['parsed_version'] = df['lids_version'].apply(parse)

    # Step 4: Sort so latest version per lot comes first
    df_sorted = df.sort_values(by=['lot', 'parsed_version'], ascending=[True, False])

    # Step 5: Keep only latest version per lot
    df = df_sorted.drop_duplicates(subset='lot', keep='first')

    return df

# ==============================================================
#  Helper: Save DataFrame
# ==============================================================

def save_processed_data(df: pd.DataFrame, output_path: str):
    """Save processed DataFrame to CSV in data/processed folder."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f" Saved: {output_path} ({len(df):,} rows)")

# ==============================================================
# 5️⃣ Full Pipeline Wrapper
# ==============================================================

def preprocess_all(active_buyers: pd.DataFrame,
                   upcoming_lots: pd.DataFrame,
                   lids_past: pd.DataFrame,
                   lids_future: pd.DataFrame,
                   output_dir: dir = "data/processed") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    This function will run preprocessing steps for active buyers, non-active buyers, popular lots and upcoming lots.
    """
    print("\n Starting preprocessing pipeline...\n")

    # Lids data
    print("\nCleaning Lids Data\n")
    lids_past_clean = clean_lids_data(lids_past)
    lids_future_clean = clean_lids_data(lids_future)

    # Active buyers
    print("\nCleaning Active buyers\n")
    active_buyers = clean_active_buyers(active_buyers)
    active_buyers = pd.merge(active_buyers, lids_past_clean,  left_on='lot_nbr', right_on='lot')
    save_processed_data(active_buyers, os.path.join(output_dir, "active_buyers.csv"))

    print("\nCleaning Upcoming Lots\n")
    upcoming_lots = clean_upcoming_lots(upcoming_lots)
    upcoming_lots = pd.merge(upcoming_lots, lids_future_clean, left_on='lot_nbr', right_on='lot')
    save_processed_data(upcoming_lots, os.path.join(output_dir, "upcoming_lots.csv"))

    return active_buyers, upcoming_lots


def main():
    active_buyers = pd.read_csv("data/raw/active_buyers.csv")
    nonactive_buyers = pd.read_csv("data/raw/non_active_buyers.csv")
    popular_lots = pd.read_csv("data/raw/popular_lots.csv")
    upcoming_lots = pd.read_csv("data/raw/upcoming_lots.csv")

    preprocess_all(active_buyers, nonactive_buyers, popular_lots, upcoming_lots)

if __name__ == "__main__":
    main()
