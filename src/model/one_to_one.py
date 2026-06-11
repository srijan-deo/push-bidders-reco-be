import os
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import manhattan_distances
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from sklearn.metrics.pairwise import cosine_similarity
from concurrent.futures import ProcessPoolExecutor, as_completed

def safe_cosine_similarity_with_zero_handling(vecs_a, vec_b):
    vecs_a = np.nan_to_num(vecs_a, nan=0.0, posinf=0.0, neginf=0.0)
    vec_b = np.nan_to_num(vec_b, nan=0.0, posinf=0.0, neginf=0.0)

    vecs_a = np.clip(vecs_a, -1e6, 1e6)
    vec_b = np.clip(vec_b, -1e6, 1e6)

    norms_a = np.linalg.norm(vecs_a, axis=1)
    norm_b = np.linalg.norm(vec_b)

    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        dot_products = vecs_a @ vec_b.reshape(-1)
        denom = norms_a * norm_b
        similarities = np.where(
            denom == 0,
            np.where(norms_a == 0, 1.0, 0.0),
            dot_products / denom
        )

    return similarities

import numpy as np
import pandas as pd
from tqdm import tqdm


# ==================================================
# 1) PREP: BE LOOKUP (build once)
# ==================================================
def build_be_lookup(be_logic):
    be = be_logic.copy()
    be.columns = [c.strip() for c in be.columns]
    be["Vehicle Location"] = be["Vehicle Location"].astype(str).str.strip().str.upper()

    for c in be.columns:
        if c != "Vehicle Location":
            be[c] = be[c].astype(str).str.strip().str.upper().eq("YES")

    eligibility = {
        (row["Vehicle Location"], col): bool(row[col])
        for _, row in be.iterrows()
        for col in be.columns
        if col != "Vehicle Location"
    }
    return eligibility


# ==================================================
# 2) PREP: UPCOMING DF NORMALIZATION + FAST INDICES
# ==================================================
def prepare_upcoming_df_and_indices(upcoming_df):
    df = upcoming_df.copy()

    df["lot_year"] = df["lot_year"].astype(int)
    df["lot_make_cd"] = df["lot_make_cd"].astype(str).str.strip().str.upper()
    df["grp_model"] = df["grp_model"].astype(str).str.strip().str.upper()
    df["lot_state"] = df["lot_state"].astype(str).str.strip().str.upper()
    df["lot_title"] = df["lot_title"].astype(str).str.strip().str.upper()

    # preserve original BE logic behavior:
    # one place in your code used full lot_state, another used [:2].
    # this column supports the BE function that uses first 2 chars.
    df["_veh_loc"] = df["lot_state"].str[:2]

    df["_title_type"] = np.where(
        df["lot_title"].str.contains("CLEAN", na=False),
        "Clean",
        "Salvage"
    )

    # fast reusable indices
    idx_year_mm = {}
    idx_mm = {}
    idx_state_title = {}
    idx_ymm = {}

    # optional global helper for state/title exact retrieval
    for i, row in df[["lot_year", "lot_make_cd", "grp_model", "lot_state", "lot_title"]].iterrows():
        year = row["lot_year"]
        make = row["lot_make_cd"]
        model = row["grp_model"]
        state = row["lot_state"]
        title = row["lot_title"]

        idx_ymm.setdefault((year, make, model), []).append(i)
        idx_year_mm.setdefault((year, make, model), []).append(i)
        idx_mm.setdefault((make, model), []).append(i)
        idx_state_title.setdefault((state, title), []).append(i)

    return df, {
        "IDX_YMM": idx_ymm,
        "IDX_YEAR_MM": idx_year_mm,
        "IDX_MM": idx_mm,
        "IDX_STATE_TITLE": idx_state_title,
    }


# ==================================================
# 3) FAST BE FILTER FACTORY
# ==================================================
def build_be_filter_fast(eligibility, buyer_type):
    bt_key = str(buyer_type).strip().title()

    def be_filter(df):
        if df is None or df.empty:
            return df

        if "_veh_loc" in df.columns:
            veh_loc = df["_veh_loc"]
        else:
            veh_loc = df["lot_state"].astype(str).str.strip().str.upper().str[:2]

        if "_title_type" in df.columns:
            title_type = df["_title_type"]
        else:
            title_type = np.where(
                df["lot_title"].astype(str).str.upper().str.contains("CLEAN", na=False),
                "Clean",
                "Salvage"
            )

        key_series = pd.Series(list(zip(veh_loc, bt_key + " - " + pd.Series(title_type, index=df.index))), index=df.index)
        mask = key_series.map(eligibility).fillna(False).to_numpy()

        return df[mask]

    return be_filter


# ==================================================
# 4) MAIN RECOMMENDER (LOGIC PRESERVED)
# ==================================================
def recommend_lots_for_buyer_fast(
    buyer_id,
    buyer_lots_df,
    upcoming_df_prepared,
    fast_indices,
    eligibility,
    active_buyers=None,
    top_k=6
):
    """
    Same logic/order:
    YMM+STATE+TITLE → YEAR±2+MM+STATE+TITLE → YMM+BE →
    YEAR±2+MM+BE (TITLE PRIORITY) → YEAR±2+MM+BE →
    MM+STATE+TITLE → MM+BE → STATE+TITLE → BE → GLOBAL
    """

    # --------------------------------------------------
    # Extract lot states / titles
    # --------------------------------------------------
    if active_buyers is not None:
        ab = active_buyers[active_buyers["buyer_nbr"] == buyer_id]

        lot_states = ab["lot_state"].astype(str).str.strip().str.upper().unique().tolist()
        lot_titles = ab["lot_title"].astype(str).str.strip().str.upper().unique().tolist()

        if 'mbr_lic_type' in ab.columns:
            buyer_type = ab['mbr_lic_type'].iloc[0]
        elif 'buyer_type' in ab.columns:
            buyer_type = ab['buyer_type'].iloc[0]
        else:
            raise ValueError("Neither 'mbr_lic_type' nor 'buyer_type' found in active_buyers")

    else:
        lot_states = buyer_lots_df["lot_state"].astype(str).str.strip().str.upper().unique().tolist()
        lot_titles = buyer_lots_df["lot_title"].astype(str).str.strip().str.upper().unique().tolist()

        # ✅ FIX: use buyer_lots_df (not ab)
        if 'mbr_lic_type' in buyer_lots_df.columns:
            buyer_type = buyer_lots_df['mbr_lic_type'].iloc[0]
        elif 'buyer_type' in buyer_lots_df.columns:
            buyer_type = buyer_lots_df['buyer_type'].iloc[0]
        else:
            raise ValueError("Neither 'mbr_lic_type' nor 'buyer_type' found in buyer_lots_df")

    buyer_title_types = ["Clean" if "CLEAN" in t else "Salvage" for t in lot_titles]

    buyer_lots_df = buyer_lots_df.copy()
    buyer_lots_df["lot_year"] = buyer_lots_df["lot_year"].astype(int)
    buyer_lots_df["lot_make_cd"] = buyer_lots_df["lot_make_cd"].astype(str).str.strip().str.upper()
    buyer_lots_df["grp_model"] = buyer_lots_df["grp_model"].astype(str).str.strip().str.upper()

    be_filter = build_be_filter_fast(eligibility, buyer_type)

    results = []
    used_lots = set()
    used_original_lots = set()

    damage_cols = [
        col for col in buyer_lots_df.columns
        if col.endswith("Damage") or col.endswith("Detected")
    ]
    base_cols = ["lot_nbr", "acv"] + damage_cols

    IDX_YMM = fast_indices["IDX_YMM"]
    IDX_YEAR_MM = fast_indices["IDX_YEAR_MM"]
    IDX_MM = fast_indices["IDX_MM"]
    IDX_STATE_TITLE = fast_indices["IDX_STATE_TITLE"]

    # --------------------------------------------------
    # Fast subset helpers
    # --------------------------------------------------
    def unique_indices(idxs):
        if not idxs:
            return []
        return list(dict.fromkeys(idxs))

    def filter_used(df):
        if df is None or df.empty:
            return None
        out = df[~df["lot_nbr"].map(used_lots.__contains__)]
        return None if out.empty else out

    def get_candidates_from_idxs(idxs):
        idxs = unique_indices(idxs)
        if not idxs:
            return None
        cands = upcoming_df_prepared.iloc[idxs]
        return filter_used(cands)

    # --------------------------------------------------
    # Indexed matching helper
    # --------------------------------------------------
    def get_top_matches(input_vec, year, make, model, k=1):
        candidates = None
        source = None

        # --------------------------------------------------
        # 1️⃣ YMM + STATE + TITLE
        # --------------------------------------------------
        temp_idxs = []
        for t in lot_titles:
            for s in lot_states:
                # preserve original intent via exact lookup on prepared df
                temp = IDX_YMM.get((year, make, model), [])
                if temp:
                    sub = upcoming_df_prepared.iloc[temp]
                    sub = sub[(sub["lot_state"].isin([s])) & (sub["lot_title"].isin([t]))]
                    temp_idxs.extend(sub.index.tolist())

        candidates = get_candidates_from_idxs(temp_idxs)
        if candidates is not None:
            source = "YMM+STATE+TITLE"

        # --------------------------------------------------
        # 2️⃣ YEAR ±2 + MM + STATE + TITLE
        # --------------------------------------------------
        if candidates is None:
            temp_idxs = []
            for yr in range(year - 2, year + 3):
                temp_idxs.extend(IDX_YEAR_MM.get((yr, make, model), []))

            subset = get_candidates_from_idxs(temp_idxs)
            if subset is not None:
                subset = subset[
                    subset["lot_state"].isin(lot_states) &
                    subset["lot_title"].isin(lot_titles)
                ]
                if not subset.empty:
                    candidates = subset
                    source = "YEAR±2+MM+STATE+TITLE"

        # --------------------------------------------------
        # 3️⃣ YMM + BE
        # --------------------------------------------------
        if candidates is None:
            subset = get_candidates_from_idxs(IDX_YMM.get((year, make, model), []))
            if subset is not None:
                subset = be_filter(subset)
                if subset is not None and not subset.empty:
                    candidates = subset
                    source = "YMM+BE"

        # --------------------------------------------------
        # 4️⃣ YEAR ±2 + MM + BE (TITLE PRIORITY)
        # --------------------------------------------------
        if candidates is None:
            temp_idxs = []
            for yr in range(year - 2, year + 3):
                temp_idxs.extend(IDX_YEAR_MM.get((yr, make, model), []))

            subset = get_candidates_from_idxs(temp_idxs)
            if subset is not None:
                subset = be_filter(subset)
                if subset is not None and not subset.empty:
                    subset = subset[subset["_title_type"].isin(buyer_title_types)]
                    if not subset.empty:
                        candidates = subset
                        source = "YEAR±2+MM+BE_TITLE"

        # --------------------------------------------------
        # 5️⃣ YEAR ±2 + MM + BE
        # --------------------------------------------------
        if candidates is None:
            temp_idxs = []
            for yr in range(year - 2, year + 3):
                temp_idxs.extend(IDX_YEAR_MM.get((yr, make, model), []))

            subset = get_candidates_from_idxs(temp_idxs)
            if subset is not None:
                subset = be_filter(subset)
                if subset is not None and not subset.empty:
                    candidates = subset
                    source = "YEAR±2+MM+BE"

        # --------------------------------------------------
        # 6️⃣ MM + STATE + TITLE
        # --------------------------------------------------
        if candidates is None:
            temp_idxs = IDX_MM.get((make, model), [])
            subset = get_candidates_from_idxs(temp_idxs)
            if subset is not None:
                subset = subset[
                    subset["lot_state"].isin(lot_states) &
                    subset["lot_title"].isin(lot_titles)
                ]
                if not subset.empty:
                    candidates = subset
                    source = "MM+STATE+TITLE"

        # --------------------------------------------------
        # 7️⃣ MM + BE
        # --------------------------------------------------
        if candidates is None:
            subset = get_candidates_from_idxs(IDX_MM.get((make, model), []))
            if subset is not None:
                subset = be_filter(subset)
                if subset is not None and not subset.empty:
                    candidates = subset
                    source = "MM+BE"

        # --------------------------------------------------
        # 8️⃣ STATE + TITLE
        # --------------------------------------------------
        if candidates is None:
            temp_idxs = []
            for s in lot_states:
                for t in lot_titles:
                    temp_idxs.extend(IDX_STATE_TITLE.get((s, t), []))

            subset = get_candidates_from_idxs(temp_idxs)
            if subset is not None and not subset.empty:
                candidates = subset
                source = "STATE+TITLE"

        # --------------------------------------------------
        # 9️⃣ BE
        # --------------------------------------------------
        if candidates is None:
            subset = filter_used(upcoming_df_prepared)
            if subset is not None:
                subset = be_filter(subset)
                if subset is not None and not subset.empty:
                    candidates = subset
                    source = "BE"

        # --------------------------------------------------
        # 🔟 GLOBAL
        # --------------------------------------------------
        if candidates is None:
            subset = filter_used(upcoming_df_prepared)
            if subset is None:
                return [], "GLOBAL"
            candidates = subset
            source = "GLOBAL"

        # --------------------------------------------------
        # Similarity ranking
        # --------------------------------------------------
        candidates = candidates[base_cols]
        candidate_vecs = candidates[["acv"] + damage_cols].to_numpy()

        similarities = safe_cosine_similarity_with_zero_handling(
            candidate_vecs,
            input_vec.reshape(1, -1)
        )

        candidates = candidates.assign(cosine_similarity=similarities)
        top = candidates.nlargest(k, "cosine_similarity")

        return top.to_dict("records"), source

    # --------------------------------------------------
    # STEP 1: Per original lot
    # --------------------------------------------------
    for _, row in buyer_lots_df.iterrows():
        if len(results) >= top_k:
            break

        original_lot = int(row["original_lot"])
        if original_lot in used_original_lots:
            continue

        input_vec = np.array([[row["acv"]] + row[damage_cols].tolist()])
        year, make, model = row["lot_year"], row["lot_make_cd"], row["grp_model"]

        top_matches, src = get_top_matches(input_vec, year, make, model)

        if top_matches:
            match = top_matches[0]
            results.append({
                "input_buyer_nbr": buyer_id,
                "original_lot": original_lot,
                "recommended_lot": int(match["lot_nbr"]),
                "cosine_similarity": float(match["cosine_similarity"]),
                "source": src
            })
            used_lots.add(match["lot_nbr"])
            used_original_lots.add(original_lot)

    # --------------------------------------------------
    # STEP 2: Most recent fallback
    # --------------------------------------------------
    if len(results) < top_k:
        most_recent = buyer_lots_df.sort_values("bid_dttm", ascending=False).iloc[0]
        input_vec = np.array([[most_recent["acv"]] + most_recent[damage_cols].tolist()])
        year, make, model = most_recent["lot_year"], most_recent["lot_make_cd"], most_recent["grp_model"]
        original_lot = int(most_recent["original_lot"])

        while len(results) < top_k:
            top_matches, src = get_top_matches(input_vec, year, make, model)
            if not top_matches:
                break

            match = top_matches[0]
            results.append({
                "input_buyer_nbr": buyer_id,
                "original_lot": original_lot,
                "recommended_lot": int(match["lot_nbr"]),
                "cosine_similarity": float(match["cosine_similarity"]),
                "source": src
            })
            used_lots.add(match["lot_nbr"])

    # --------------------------------------------------
    # STEP 3: Random global filler
    # --------------------------------------------------
    if len(results) < top_k:
        remaining = top_k - len(results)
        filler = upcoming_df_prepared[
            ~upcoming_df_prepared["lot_nbr"].map(used_lots.__contains__)
        ].sample(
            n=min(remaining, (~upcoming_df_prepared["lot_nbr"].map(used_lots.__contains__)).sum()),
            random_state=42
        )

        for _, row in filler.iterrows():
            results.append({
                "input_buyer_nbr": buyer_id,
                "original_lot": original_lot,
                "recommended_lot": int(row["lot_nbr"]),
                "cosine_similarity": 0.0,
                "source": "GLOBAL"
            })
            used_lots.add(row["lot_nbr"])

    return results


# ==================================================
# 5) PARALLEL/BATCH DRIVER (same outer behavior)
# ==================================================
def refine_recommendations_parallel_per_buyer_fast(
    reco_df,
    upcoming_df,
    be_logic,
    active_buyers=None,
    batch_size=25
):
    # --------------------------------------------------
    # Normalize input reco_df once
    # --------------------------------------------------
    reco_df = reco_df.rename(columns=lambda col: col.strip())

    reco_df = reco_df.rename(columns={
        col: "input_buyer_nbr" for col in reco_df.columns if col.lower() == "buyer_nbr"
    } | {
        col: "original_lot" for col in reco_df.columns
        if col.lower() in ["lot_nbr", "recommended_lot"]
    })

    # --------------------------------------------------
    # Build global reusable objects once
    # --------------------------------------------------
    eligibility = build_be_lookup(be_logic)
    upcoming_df_prepared, fast_indices = prepare_upcoming_df_and_indices(upcoming_df)

    results = []
    grouped = list(reco_df.groupby("input_buyer_nbr"))

    def batched(iterable, size):
        for i in range(0, len(iterable), size):
            yield iterable[i:i + size]

    # --------------------------------------------------
    # Batched processing
    # --------------------------------------------------
    for batch in tqdm(
        batched(grouped, batch_size),
        total=(len(grouped) + batch_size - 1) // batch_size,
        desc="Refining recos (batched)"
    ):
        for buyer_id, group_df in batch:
            try:
                out = recommend_lots_for_buyer_fast(
                    buyer_id=buyer_id,
                    buyer_lots_df=group_df,
                    upcoming_df_prepared=upcoming_df_prepared,
                    fast_indices=fast_indices,
                    eligibility=eligibility,
                    active_buyers=active_buyers,
                    top_k=6
                )
                results.extend(out)
            except Exception as e:
                print(f"⚠️ Skipped buyer due to error: {e}")

    return pd.DataFrame(results)




# ==============================================================
# Save to Excel Helper (Always Excel)
# ==============================================================
def save_processed_data(df: pd.DataFrame, output_path: str):
    """Save a DataFrame to Excel (.xlsx) in a given path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    print(f"\nSaved processed data to {output_path} ({len(df):,} rows)")

if __name__ == "__main__":

    upcoming_lots = pd.read_csv("data/processed/upcoming_lots.csv")

    # TEST data low group
    data_low_test = pd.read_csv("data/split/one_to_one_test.csv")
    recommended_upcoming_df_lt6_test = refine_recommendations_parallel_per_buyer(data_low_test, upcoming_lots)
    save_processed_data(recommended_upcoming_df_lt6_test, "data/results/onetoone_test_reco_test.xlsx")
    #
    #HOLDOUT data low group (would have)
    data_low_holdout = pd.read_csv("data/split/one_to_one_holdout.csv")
    recommended_upcoming_df_lt6_holdout = refine_recommendations_parallel_per_buyer(data_low_holdout, upcoming_lots)
    save_processed_data(recommended_upcoming_df_lt6_holdout, "data/results/onetoone_holdout_would_have_reco.xlsx")


    # ## Active buyers
    active_buyers = pd.read_csv("data/raw/active_buyers.csv")
    # # TEST data high group
    data_cf_test = pd.read_excel("data/past_reco/cf_test_reco.xlsx")
    recommended_upcoming_df_gt6 = refine_recommendations_parallel_per_buyer(data_cf_test, upcoming_lots, active_buyers)
    save_processed_data(recommended_upcoming_df_gt6, "data/results/cf_test_reco_test.xlsx")

    # HOLDOUT data high group (would have)
    data_cf_holdout = pd.read_excel("data/past_reco/cf_holdout_would_have_reco.xlsx")
    recommended_upcoming_df_gt6_holdout = refine_recommendations_parallel_per_buyer(data_cf_holdout, upcoming_lots,active_buyers)
    save_processed_data(recommended_upcoming_df_gt6_holdout, "data/results/cf_holdout_would_have_reco.xlsx")