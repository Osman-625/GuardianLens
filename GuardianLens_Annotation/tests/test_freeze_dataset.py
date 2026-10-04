from scripts.freeze_dataset import build_manifest


def test_manifest_counts_labels_and_rows():
    final_rows = [
        {"listing_id": "L1", "final_label": "legitimate", "platform": "carousell"},
        {"listing_id": "L2", "final_label": "scam_fraud", "platform": "mudah"},
        {"listing_id": "L3", "final_label": "legitimate", "platform": "carousell"},
    ]
    manifest = build_manifest(final_rows, version="v1")
    assert manifest["row_count"] == 3
    assert manifest["label_distribution"]["legitimate"] == 2
    assert manifest["label_distribution"]["scam_fraud"] == 1
    assert manifest["platform_distribution"]["carousell"] == 2
    assert manifest["version"] == "v1"
