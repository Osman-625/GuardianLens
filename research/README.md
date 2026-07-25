# Research data boundary

This directory contains schemas and human-facing study materials only. The application and automated tests must never create dataset labels, annotation rows, adjudications, split assignments, consent records, or study responses.

Expected flow:

1. Manual browsing of Mudah.my and Carousell.
2. Structured entry through the existing collection log tool.
3. Blind A1 and A2 labelling against the frozen rubric.
4. Human adjudication where required.
5. Export, PII scrub verification, and controlled import into the `research` schema.
6. Grouped and duplicate-aware split generation after Gate A.

Store actual data under ignored directories such as `research/data/` and `research/exports/`. Never commit participant contact details or raw marketplace identifiers.
