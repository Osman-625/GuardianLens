# Research data boundary

This directory contains schemas and human-facing study materials only. The application and automated tests must never create dataset labels, annotation rows, adjudications, split assignments, consent records, or study responses.

Start with [DATA_COLLECTION_GUIDELINE.md](DATA_COLLECTION_GUIDELINE.md) and obtain the
Gate 0 approvals before copying listing text or images. The initial labeling rules are in
[LABELLING_RUBRIC_V1.md](LABELLING_RUBRIC_V1.md); they remain a draft until supervisor
approval and annotator calibration.

Expected flow:

1. Supervisor/ethics review and written data-reuse permission.
2. Authorized manual collection through the existing collection log tool.
3. Blind A1 and A2 labelling against the frozen rubric.
4. Human adjudication where required.
5. Export, PII scrub verification, and controlled import into the `research` schema.
6. Grouped and duplicate-aware split generation after Gate A.

Store actual data under ignored directories such as `research/data/` and `research/exports/`. Never commit participant contact details or raw marketplace identifiers.
