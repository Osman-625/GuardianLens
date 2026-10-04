from scripts.compute_agreement import confusion_matrix, severe_disagreements, cohens_kappa, confidence_distribution


def test_confusion_matrix_counts_every_pair_including_agreements():
    pairs = [("legitimate", "legitimate"), ("legitimate", "suspicious"), ("scam_fraud", "scam_fraud")]
    cm = confusion_matrix(pairs)
    assert cm[("legitimate", "legitimate")] == 1
    assert cm[("legitimate", "suspicious")] == 1
    assert cm[("scam_fraud", "scam_fraud")] == 1
    assert cm[("legitimate", "scam_fraud")] == 0


def test_severe_disagreements_flags_opposite_ends_only():
    pairs = [
        ("legitimate", "scam_fraud"),
        ("scam_fraud", "legitimate"),
        ("legitimate", "suspicious"),
        ("legitimate", "legitimate"),
    ]
    severe = severe_disagreements(pairs)
    assert len(severe) == 2
    assert ("legitimate", "scam_fraud") in severe
    assert ("scam_fraud", "legitimate") in severe


def test_kappa_unchanged_for_perfect_agreement():
    pairs = [("legitimate", "legitimate")] * 5 + [("scam_fraud", "scam_fraud")] * 5
    assert cohens_kappa(pairs) == 1.0


def test_confidence_distribution_reports_min_max_mean():
    a_rows = {"L1": {"confidence": "2"}, "L2": {"confidence": "4"}}
    b_rows = {"L1": {"confidence": "3"}, "L2": {"confidence": "5"}}
    dist = confidence_distribution(a_rows, b_rows, ["L1", "L2"])
    assert dist["a"]["min"] == 2.0
    assert dist["a"]["max"] == 4.0
    assert dist["a"]["mean"] == 3.0
    assert dist["b"]["mean"] == 4.0
