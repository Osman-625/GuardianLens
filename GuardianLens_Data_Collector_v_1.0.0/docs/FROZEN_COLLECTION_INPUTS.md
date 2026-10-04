# Collection backup and frozen inputs

The live collector's automatic annotation-export callbacks are disabled in
`collection_handoff.py`. This takes effect on a process's next normal start; the
freeze command never restarts or signals the live app. Existing annotation exports
and the legacy explicit exporter are preserved. Collection/review logic and schema
are unchanged. No configuration or retention-policy change is required.

From the project root, using its existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -B scripts\freeze_collection_inputs.py observe
.\.venv\Scripts\python.exe -B scripts\freeze_collection_inputs.py create
.\.venv\Scripts\python.exe -B scripts\freeze_collection_inputs.py verify --snapshot "<generation directory>"
.\.venv\Scripts\python.exe -B scripts\freeze_collection_inputs.py restore --snapshot "<generation directory>" --destination "<new isolated directory>"
```

The create command uses SQLite's online backup API through a read-only connection,
including committed WAL content. It observes task states and logical database and
asset inventories before copying. If work is active or changes during copying,
it refuses to certify the attempt; it never stops another process. Coordinate an
idle window if that happens. All failed copies remain marked incomplete.

Data lives under `data/backups/frozen_inputs/<UTC timestamp>_<random suffix>/`:

- `private/backup/project/data/collector.sqlite3`: all tables and collection states.
- `private/backup/project/data/`: original product-image bytes and remaining private evidence.
- `private/workspace/`: current source/configuration/docs, including uncommitted content.
- `private/secrets/`: `.env`, local token and provider override, separate from exports.
- `private/handoff_source/`: captured existing handoff for reconciliation.
- `private/candidates/`: exact approved listing rows and their image associations.
- `private/reports/`: every-record checks, image checks, handoff differences and restore proof.
- `private/review/index.html`: local, read-only approved-record evidence browser.
- `public/`: minimal numeric/UUID index, completeness, dictionary, summary and protocol.
- `manifest.json`: SHA-256 and exact size for every package file; the completion marker.

The command restores the full collection DB and available runtime assets under
`data/backups/restore_checks/<same generation>/project/`, checks all restored bytes,
database integrity, foreign keys and every table's logical contents. It does not
start an app or install credentials in that restored location. `restore` refuses
any destination that already exists. Source values and image bytes are never rewritten.

The asset copy uses idle-state checks, before/after metadata checks, rehashes and
database logical fingerprints. This detects observed changes; it is not an OS-wide
atomic volume snapshot or a lock preventing future writes. The source can resume
after the verified observation window without changing the frozen package. A
complete manifest is published only after restoration succeeds. The package is
immutable by convention/checksums, not a hardware-enforced write-once archive.

This local backup shares the workspace's disk and OneDrive location; it is not an
independent disaster-recovery copy. Keep the entire package private and preserve
its manifest checksum when transferring it through your approved private storage.
No upload is performed by this utility. Ignored backup paths must stay out of Git.
