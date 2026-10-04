from scripts.build_splits import assign_splits


def test_grouped_rows_never_split_across_boundaries():
    rows = [
        {"listing_id": f"L{i}", "final_label": "legitimate"} for i in range(20)
    ] + [
        {"listing_id": f"S{i}", "final_label": "scam_fraud"} for i in range(20)
    ]
    group_of = {r["listing_id"]: r["listing_id"] for r in rows}
    group_of["L0"] = "dup_group_1"
    group_of["L1"] = "dup_group_1"

    splits = assign_splits(rows, group_of, seed=42)
    split_of_id = {}
    for split_name, split_rows in splits.items():
        for r in split_rows:
            split_of_id[r["listing_id"]] = split_name

    assert split_of_id["L0"] == split_of_id["L1"], "listings in the same duplicate group must land in the same split"


def test_all_rows_accounted_for_exactly_once():
    rows = [{"listing_id": f"L{i}", "final_label": "legitimate"} for i in range(50)]
    group_of = {r["listing_id"]: r["listing_id"] for r in rows}
    splits = assign_splits(rows, group_of, seed=42)
    all_out_ids = [r["listing_id"] for s in splits.values() if s is not splits.get("clean_validation") for r in s]
    non_clean_ids = [r["listing_id"] for name, s in splits.items() if name != "clean_validation" for r in s]
    assert sorted(non_clean_ids) == sorted(r["listing_id"] for r in rows)
    assert len(non_clean_ids) == len(set(non_clean_ids))


def test_deterministic_with_fixed_seed():
    rows = [{"listing_id": f"L{i}", "final_label": "legitimate" if i % 2 == 0 else "scam_fraud"} for i in range(100)]
    group_of = {r["listing_id"]: r["listing_id"] for r in rows}
    a = assign_splits(rows, group_of, seed=42)
    b = assign_splits(rows, group_of, seed=42)
    assert [r["listing_id"] for r in a["train"]] == [r["listing_id"] for r in b["train"]]


def test_clean_validation_is_subset_of_validation():
    rows = [{"listing_id": f"L{i}", "final_label": "legitimate"} for i in range(50)]
    group_of = {r["listing_id"]: r["listing_id"] for r in rows}
    splits = assign_splits(rows, group_of, seed=42)
    val_ids = {r["listing_id"] for r in splits["validation"]}
    clean_ids = {r["listing_id"] for r in splits["clean_validation"]}
    assert clean_ids <= val_ids
