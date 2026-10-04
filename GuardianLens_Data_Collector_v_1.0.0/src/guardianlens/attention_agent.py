"""Durable, bounded preparation of needs-attention records for human review."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import threading
import time
import uuid

from .attention_evidence import (
    corroborated_ai_proposals, deterministic_proposals, input_fingerprint,
    load_evidence, protected_fields,
)
from .config import get_active_provider, provider_configured, settings
from .db import connect, now_iso, transaction
from .dedupe import metadata_signature
from .extraction_contract import EXTRACTION_SCHEMA, normalize_extracted_listing
from .pii import scrub_text
from .processor import _extractor_identity, default_extractor
from .states import transition
from .validation import FIELD_WARNING_TYPES, inspect_listing, validate_fields

ACTIVE_STATUSES = ("running", "paused", "stopping")
TERMINAL_OUTCOMES = ("ready", "awaiting_capture", "awaiting_human", "failed", "skipped")
MAX_INPUT_ATTEMPTS = 3
WATCH_INTERVAL_SECONDS = 15


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _revision(row: dict) -> str:
    return "snapshot:" + hashlib.sha256(_json(row).encode("utf-8")).hexdigest()


def _finding(code: str, message: str, action: str = "human", field: str | None = None) -> dict:
    return {"code": code, "field": field, "message": message, "action": action}


def _outcome(findings: list[dict]) -> str:
    if not findings:
        return "ready"
    return "awaiting_capture" if any(item.get("action") == "capture" for item in findings) else "awaiting_human"


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied is not evidence that another process died.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AttentionAgentManager:
    def __init__(self, *, extractor_factory=None) -> None:
        self.extractor_factory = extractor_factory
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._owner_id = str(uuid.uuid4())

    def _lease_until(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=max(120, settings.request_timeout_seconds + 90))).isoformat()

    @staticmethod
    def _external_busy(con) -> bool:
        processor = con.execute("SELECT command FROM processor_control WHERE control_id=1").fetchone()
        if processor and processor["command"] in ACTIVE_STATUSES:
            return True
        for table in ("capture_batches", "seller_retry_batches", "processing_runs"):
            if con.execute(f"SELECT 1 FROM {table} WHERE status IN ('running','paused','stopping') LIMIT 1").fetchone():
                return True
        return False

    @staticmethod
    def _eligible(con, row: dict, selection: dict) -> bool:
        if row["status"] == "needs_attention":
            return not selection.get("recovery_batch_id")
        if row["status"] != "captured" or not selection.get("recovery_batch_id"):
            return False
        return bool(con.execute(
            """SELECT 1 FROM seller_retry_items retry
               JOIN seller_retry_batches batch ON batch.retry_batch_id=retry.retry_batch_id
               WHERE retry.listing_id=? AND retry.retry_batch_id=? AND retry.status='succeeded'
                 AND batch.status IN ('stopped','completed')
                 AND EXISTS (SELECT 1 FROM status_history history WHERE history.listing_id=retry.listing_id
                             AND history.from_status='needs_attention' AND history.to_status='captured')""",
            (row["listing_id"], selection["recovery_batch_id"]),
        ).fetchone())

    def _selected_rows(self, con, selection: dict) -> list[dict]:
        query = "SELECT listing.* FROM listings listing WHERE listing.status=?"
        params: list = ["captured" if selection.get("recovery_batch_id") else "needs_attention"]
        if selection.get("platform"):
            query += " AND listing.platform=?"
            params.append(selection["platform"])
        if selection.get("reason"):
            query += " AND EXISTS (SELECT 1 FROM warnings w WHERE w.listing_id=listing.listing_id AND w.resolved=0 AND w.warning_type=?)"
            params.append(selection["reason"])
        query += " ORDER BY listing.captured_at,listing.listing_id"
        ids = set(selection["listing_ids"]) if selection.get("listing_ids") is not None else None
        return [row for entry in con.execute(query, params) if (row := dict(entry))
                and (ids is None or row["listing_id"] in ids) and self._eligible(con, row, selection)]

    def start(
        self, mode: str = "inspect", listing_ids: list[str] | None = None,
        platform: str | None = None, reason: str | None = None, item_limit: int | None = None,
        time_limit_minutes: int = 60, api_call_limit: int = 25, watch: bool = False,
        recovery_batch_id: str | None = None,
    ) -> dict:
        if mode not in {"inspect", "repair"}:
            raise ValueError("mode must be inspect or repair")
        if platform not in {None, "", "all", "carousell", "mudah"}:
            raise ValueError("unsupported platform")
        for name, value, minimum, maximum in (
            ("time_limit_minutes", time_limit_minutes, 1, 720),
            ("api_call_limit", api_call_limit, 0, 10000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if item_limit is not None and (isinstance(item_limit, bool) or not isinstance(item_limit, int) or not 1 <= item_limit <= 10000):
            raise ValueError("item_limit must be between 1 and 10000")
        if listing_ids is not None:
            if not isinstance(listing_ids, list) or len(listing_ids) > 10000 or any(
                not isinstance(item, str) or not item.strip() or len(item) > 64 for item in listing_ids
            ):
                raise ValueError("listing_ids must be a bounded list of listing identifiers")
            listing_ids = list(dict.fromkeys(listing_ids))
        if reason is not None and (not isinstance(reason, str) or len(reason) > 100):
            raise ValueError("reason must be a warning type")
        if recovery_batch_id is not None and (not isinstance(recovery_batch_id, str) or not recovery_batch_id or len(recovery_batch_id) > 64):
            raise ValueError("invalid recovery batch identifier")
        selection = {"listing_ids": listing_ids, "platform": platform if platform not in {"", "all"} else None,
                     "reason": reason if reason not in {"", "all"} else None, "recovery_batch_id": recovery_batch_id}
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("an attention agent is already active")
            self.recover()
            with transaction() as con:
                if con.execute("SELECT 1 FROM attention_agent_runs WHERE status IN ('running','paused','stopping') LIMIT 1").fetchone():
                    raise ValueError("resume or stop the existing attention agent run first")
                if mode == "repair" and self._external_busy(con):
                    raise ValueError("pause and stop capture, seller recovery, and preprocessing before repair")
                if recovery_batch_id and not con.execute(
                    "SELECT 1 FROM seller_retry_batches WHERE retry_batch_id=? AND status IN ('completed','stopped')",
                    (recovery_batch_id,),
                ).fetchone():
                    raise ValueError("complete or stop the seller recovery batch before extraction")
                run_id, stamp = str(uuid.uuid4()), now_iso()
                con.execute(
                    """INSERT INTO attention_agent_runs(run_id,status,mode,selection,watch,item_limit,
                       time_limit_minutes,api_call_limit,owner_id,owner_pid,lease_expires_at,created_at,started_at,updated_at)
                       VALUES(?,'running',?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, mode, _json(selection), int(watch), item_limit, time_limit_minutes, api_call_limit,
                     self._owner_id, os.getpid(), self._lease_until(), stamp, stamp, stamp),
                )
                rows = self._selected_rows(con, selection)
                if item_limit:
                    rows = rows[:item_limit]
                con.executemany(
                    """INSERT INTO attention_agent_items(item_id,run_id,listing_id,input_fingerprint,created_at,updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    [(str(uuid.uuid4()), run_id, row["listing_id"], _revision(row), stamp, stamp) for row in rows],
                )
            self._launch(run_id)
        return self.status(run_id)

    def _launch(self, run_id: str) -> None:
        self._shutdown.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, args=(run_id,), name="needs-attention-agent", daemon=True)
        self._thread.start()

    def status(self, run_id: str | None = None) -> dict:
        con = connect()
        try:
            if run_id:
                row = con.execute("SELECT * FROM attention_agent_runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    raise KeyError(run_id)
            else:
                row = con.execute("SELECT * FROM attention_agent_runs ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
            progress = {key: 0 for key in ("total", "inspected", "changed", "ready", "awaiting_capture", "awaiting_human", "failed", "skipped", "pending")}
            if not row:
                return {"run": None, "progress": progress, "items": [], "running": False}
            run = dict(row)
            run["watch"] = bool(run["watch"])
            run["selection"] = json.loads(run["selection"])
            for key in ("owner_id", "owner_pid", "lease_expires_at"):
                run.pop(key, None)
            for item in con.execute(
                "SELECT outcome,COUNT(*) total,SUM(changes<>'[]') changed FROM attention_agent_items WHERE run_id=? GROUP BY outcome",
                (run["run_id"],),
            ):
                count = item["total"]
                progress["total"] += count
                progress["changed"] += item["changed"] or 0
                if item["outcome"] in {"pending", "inspecting"}:
                    progress["pending"] += count
                else:
                    progress["inspected"] += count
                    progress[item["outcome"]] += count
            items = [self._item_data(item) for item in con.execute(
                "SELECT * FROM attention_agent_items WHERE run_id=? ORDER BY COALESCE(finished_at,started_at,created_at) DESC,rowid DESC LIMIT 100",
                (run["run_id"],),
            )]
            return {"run": run, "progress": progress, "items": items, "running": run["status"] == "running"}
        finally:
            con.close()

    @staticmethod
    def _item_data(row) -> dict:
        item = dict(row)
        for field in ("findings", "changes"):
            item[field] = json.loads(item[field])
        item.pop("lease_token", None)
        return item

    def record_history(self, listing_id: str) -> list[dict]:
        con = connect()
        try:
            return [self._item_data(item) for item in con.execute(
                """SELECT item.*,run.mode run_mode FROM attention_agent_items item
                   JOIN attention_agent_runs run ON run.run_id=item.run_id
                   WHERE item.listing_id=? ORDER BY item.created_at DESC,item.rowid DESC LIMIT 100""",
                (listing_id,),
            )]
        finally:
            con.close()

    def recoverable_listing_ids(self, run_id: str) -> list[str]:
        con = connect()
        try:
            return [item[0] for item in con.execute(
                """SELECT DISTINCT item.listing_id FROM attention_agent_items item
                   JOIN listings listing ON listing.listing_id=item.listing_id
                   WHERE item.run_id=? AND item.outcome='awaiting_capture' AND listing.status='needs_attention'
                   ORDER BY item.listing_id""", (run_id,),
            )]
        finally:
            con.close()

    def command(self, run_id: str, command: str) -> dict:
        if command not in {"pause", "resume", "stop"}:
            raise ValueError("command must be pause, resume, or stop")
        with self._lock:
            with transaction() as con:
                row = con.execute("SELECT * FROM attention_agent_runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    raise KeyError(run_id)
                if row["status"] not in ACTIVE_STATUSES:
                    raise ValueError("the attention agent run has ended")
                if command == "resume":
                    if row["status"] != "paused":
                        raise ValueError("only a paused run can resume")
                    if row["mode"] == "repair" and self._external_busy(con):
                        raise ValueError("stop other capture or processing workers before resuming repair")
                    owner_active = row["owner_id"] != self._owner_id and _pid_alive(row["owner_pid"]) and (row["lease_expires_at"] or "") > now_iso()
                    if owner_active:
                        # A separate process still owns the paused thread; its
                        # durable command loop performs the resume.
                        con.execute("UPDATE attention_agent_runs SET status='running',updated_at=? WHERE run_id=?", (now_iso(), run_id))
                    else:
                        con.execute(
                            """UPDATE attention_agent_runs SET status='running',owner_id=?,owner_pid=?,
                               lease_expires_at=?,message=NULL,updated_at=? WHERE run_id=?""",
                            (self._owner_id, os.getpid(), self._lease_until(), now_iso(), run_id),
                        )
                elif command == "pause":
                    con.execute("UPDATE attention_agent_runs SET status='paused',message='Paused by operator',updated_at=? WHERE run_id=?", (now_iso(), run_id))
                else:
                    con.execute("UPDATE attention_agent_runs SET status='stopping',updated_at=? WHERE run_id=?", (now_iso(), run_id))
            self._wake.set()
            if command == "resume" and not owner_active and not (self._thread and self._thread.is_alive()):
                self._launch(run_id)
            elif command == "stop" and not (self._thread and self._thread.is_alive()) and not _pid_alive(row["owner_pid"]):
                self._finish(run_id, "stopped", "Stopped by operator")
            elif command == "stop" and row["owner_id"] == self._owner_id and not (self._thread and self._thread.is_alive()):
                self._finish(run_id, "stopped", "Stopped by operator")
        return self.status(run_id)

    def recover(self) -> None:
        """Pause interrupted ownership without starting a thread or contacting a provider."""
        with transaction() as con:
            for row in con.execute("SELECT * FROM attention_agent_runs WHERE status IN ('running','paused','stopping')").fetchall():
                same_live_thread = row["owner_id"] == self._owner_id and self._thread and self._thread.is_alive()
                if same_live_thread:
                    continue
                expired = not row["lease_expires_at"] or row["lease_expires_at"] < now_iso()
                if _pid_alive(row["owner_pid"]) and not expired:
                    continue
                con.execute(
                    """UPDATE attention_agent_runs SET status='paused',owner_id=NULL,owner_pid=NULL,
                       lease_expires_at=NULL,message='Interrupted run recovered; resume explicitly',updated_at=? WHERE run_id=?""",
                    (now_iso(), row["run_id"]),
                )
                con.execute(
                    """UPDATE attention_agent_items SET outcome='pending',lease_token=NULL,updated_at=?
                       WHERE run_id=? AND outcome='inspecting'""", (now_iso(), row["run_id"]),
                )

    def shutdown(self) -> None:
        self._shutdown.set()
        self._wake.set()
        with transaction() as con:
            con.execute(
                """UPDATE attention_agent_runs SET status='paused',message='Application stopped; resume explicitly',updated_at=?
                   WHERE owner_id=? AND status IN ('running','stopping')""", (now_iso(), self._owner_id),
            )
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=min(settings.request_timeout_seconds + 5, 50))

    def _finish(self, run_id: str, status: str, message: str) -> None:
        with transaction() as con:
            con.execute(
                """UPDATE attention_agent_runs SET status=?,message=?,finished_at=?,updated_at=?,
                   lease_expires_at=NULL,owner_id=NULL,owner_pid=NULL WHERE run_id=?""",
                (status, message, now_iso(), now_iso(), run_id),
            )
            if status in {"stopped", "failed"}:
                con.execute(
                    """UPDATE attention_agent_items SET outcome='skipped',findings=?,finished_at=?,updated_at=?,lease_token=NULL
                       WHERE run_id=? AND outcome IN ('pending','inspecting')""",
                    (_json([_finding("run_stopped", message)]), now_iso(), now_iso(), run_id),
                )

    def _watch_append(self, con, run: dict) -> int:
        added = 0
        total = con.execute("SELECT COUNT(*) FROM attention_agent_items WHERE run_id=?", (run["run_id"],)).fetchone()[0]
        for row in self._selected_rows(con, json.loads(run["selection"])):
            if run["item_limit"] and total + added >= run["item_limit"]:
                break
            fingerprint = input_fingerprint(con, row)
            previous = con.execute(
                """SELECT 1 FROM attention_agent_items WHERE run_id=? AND listing_id=?
                   AND (input_fingerprint=? OR output_fingerprint=?) LIMIT 1""",
                (run["run_id"], row["listing_id"], fingerprint, fingerprint),
            ).fetchone()
            if previous:
                continue
            stamp = now_iso()
            con.execute(
                """INSERT INTO attention_agent_items(item_id,run_id,listing_id,input_fingerprint,created_at,updated_at)
                   VALUES(?,?,?,?,?,?)""", (str(uuid.uuid4()), run["run_id"], row["listing_id"], fingerprint, stamp, stamp),
            )
            added += 1
        return added

    def _run(self, run_id: str) -> None:
        last_tick = time.monotonic()
        try:
            while not self._shutdown.is_set():
                paused = False
                should_wait = False
                with transaction() as con:
                    record = con.execute("SELECT * FROM attention_agent_runs WHERE run_id=?", (run_id,)).fetchone()
                    if not record or record["owner_id"] != self._owner_id or record["status"] not in ACTIVE_STATUSES:
                        return
                    run = dict(record)
                    elapsed = time.monotonic() - last_tick
                    last_tick = time.monotonic()
                    con.execute(
                        "UPDATE attention_agent_runs SET elapsed_seconds=elapsed_seconds+?,lease_expires_at=?,updated_at=? WHERE run_id=?",
                        (0 if run["status"] == "paused" else elapsed, self._lease_until(), now_iso(), run_id),
                    )
                    if run["status"] == "paused":
                        paused = True
                    elif run["status"] == "stopping":
                        pass
                    elif run["elapsed_seconds"] + elapsed >= run["time_limit_minutes"] * 60:
                        run["status"] = "stopping"
                        run["message"] = "Time limit reached; remaining records can be selected in another run"
                    elif run["mode"] == "repair" and self._external_busy(con):
                        con.execute("UPDATE attention_agent_runs SET status='paused',message='Paused: another worker is active' WHERE run_id=?", (run_id,))
                        paused = True
                    else:
                        item = con.execute(
                            "SELECT * FROM attention_agent_items WHERE run_id=? AND outcome='pending' ORDER BY created_at,rowid LIMIT 1", (run_id,),
                        ).fetchone()
                        if not item and run["watch"]:
                            self._watch_append(con, run)
                            item = con.execute(
                                "SELECT * FROM attention_agent_items WHERE run_id=? AND outcome='pending' ORDER BY created_at,rowid LIMIT 1", (run_id,),
                            ).fetchone()
                            should_wait = not item
                        if item:
                            item = dict(item)
                            item["lease_token"] = str(uuid.uuid4())
                            con.execute(
                                """UPDATE attention_agent_items SET outcome='inspecting',attempt_count=attempt_count+1,
                                   lease_token=?,started_at=?,updated_at=? WHERE item_id=? AND outcome='pending'""",
                                (item["lease_token"], now_iso(), now_iso(), item["item_id"]),
                            )
                if paused or should_wait:
                    self._wake.wait(WATCH_INTERVAL_SECONDS)
                    self._wake.clear()
                    continue
                if run["status"] == "stopping":
                    self._finish(run_id, "stopped", run.get("message") or "Stopped by operator")
                    return
                if not item:
                    self._finish(run_id, "completed", "All selected records inspected")
                    return
                self._process(run, item)
        except Exception:
            # Raw captures/provider errors can contain personal information or
            # credentials. Persist only a stable operational failure category.
            self._finish(run_id, "failed", "Agent worker interrupted by an internal error; inspect local tests and resume with a new run")
        finally:
            with transaction() as con:
                con.execute(
                    """UPDATE attention_agent_runs SET status='paused',owner_id=NULL,owner_pid=NULL,lease_expires_at=NULL,
                       updated_at=? WHERE run_id=? AND owner_id=? AND status IN ('running','paused','stopping')""",
                    (now_iso(), run_id, self._owner_id),
                )
                con.execute(
                    """UPDATE attention_agent_items SET outcome='pending',lease_token=NULL,updated_at=?
                       WHERE run_id=? AND outcome='inspecting'""", (now_iso(), run_id),
                )

    def _complete_item(self, con, item: dict, outcome: str, findings: list, changes: list | None = None, output_fingerprint: str | None = None) -> None:
        con.execute(
            """UPDATE attention_agent_items SET outcome=?,findings=?,changes=?,output_fingerprint=?,
               finished_at=?,updated_at=?,lease_token=NULL WHERE item_id=? AND lease_token=?""",
            (outcome, _json(findings), _json(changes or []), output_fingerprint, now_iso(), now_iso(), item["item_id"], item["lease_token"]),
        )

    def _process(self, run: dict, item: dict) -> None:
        selection = json.loads(run["selection"])
        try:
            with transaction() as con:
                record = con.execute("SELECT * FROM listings WHERE listing_id=?", (item["listing_id"],)).fetchone()
                row = dict(record) if record else None
                if not row or not self._eligible(con, row, selection):
                    self._complete_item(con, item, "skipped", [_finding("state_changed", "Listing is no longer eligible")])
                    return
                if con.execute("SELECT 1 FROM review_actions WHERE listing_id=? AND action='review_session' AND finished_at IS NULL", (row["listing_id"],)).fetchone():
                    self._complete_item(con, item, "skipped", [_finding("human_review_active", "A human review session is active")])
                    return
                if item["input_fingerprint"].startswith("snapshot:") and item["input_fingerprint"] != _revision(row):
                    self._complete_item(con, item, "skipped", [_finding("input_changed", "Listing changed after the run was selected")])
                    return
                evidence = load_evidence(row)
                fingerprint = input_fingerprint(con, row, evidence)
                if not item["input_fingerprint"].startswith("snapshot:") and fingerprint != item["input_fingerprint"]:
                    self._complete_item(con, item, "skipped", [_finding("input_changed", "Capture or listing changed before this attempt")])
                    return
                item["input_fingerprint"] = fingerprint
                con.execute("UPDATE attention_agent_items SET input_fingerprint=? WHERE item_id=?", (fingerprint, item["item_id"]))
                findings = inspect_listing(con, row)
                protected = protected_fields(con, row["listing_id"])
                previous = con.execute(
                    """SELECT item.* FROM attention_agent_items item JOIN attention_agent_runs run ON run.run_id=item.run_id
                       WHERE item.listing_id=? AND item.item_id<>? AND run.mode='repair'
                         AND (item.input_fingerprint=? OR item.output_fingerprint=?)
                         AND item.outcome IN ('awaiting_capture','awaiting_human','failed','ready')
                       ORDER BY item.finished_at DESC,item.rowid DESC""",
                    (row["listing_id"], item["item_id"], fingerprint, fingerprint),
                ).fetchall()
            if run["mode"] == "inspect":
                with transaction() as con:
                    self._complete_item(con, item, _outcome(findings), findings, output_fingerprint=fingerprint)
                return
            fields = {finding["field"] for finding in findings if finding.get("field") in EXTRACTION_SCHEMA and finding["code"] in FIELD_WARNING_TYPES}
            extras = [_finding("human_correction_protected", "A prior human correction needs human review", field=field) for field in sorted(fields & protected)]
            fields -= protected
            proposals = deterministic_proposals(row, evidence, fields)
            candidate = dict(row)
            for field, proposal in proposals.items():
                candidate[field] = proposal["value"]
            invalid_after_rules = {finding["field"] for finding in validate_fields(candidate)}
            proposals = {field: proposal for field, proposal in proposals.items() if field not in invalid_after_rules}
            remaining = fields - set(proposals)
            no_progress = any(previous_item["changes"] == "[]" and previous_item["outcome"] != "failed" for previous_item in previous)
            calls_for_input = sum(previous_item["api_called"] for previous_item in previous) + item.get("api_called", 0)
            can_extract = (remaining and not no_progress and calls_for_input < MAX_INPUT_ATTEMPTS
                           and evidence.get("screenshot_path") and (evidence["listing_text"] or evidence["seller_text"])
                           and (self.extractor_factory is not None or provider_configured(get_active_provider())))
            provider_failed = False
            if can_extract and self._reserve_call(run["run_id"], item):
                try:
                    extractor = self.extractor_factory() if self.extractor_factory else default_extractor()
                    # Restrict the adapter input to available captured evidence;
                    # accepted values still pass independent corroboration below.
                    extracted = normalize_extracted_listing(extractor.extract(
                        evidence["screenshot_path"], row["platform"], row["page_title"],
                        [entry["name"] for entry in settings.categories()], source_url=row["source_url"],
                        visible_text=evidence["listing_text"], seller_visible_text=evidence["seller_text"],
                        captured_at=evidence.get("seller_captured_at") or row["captured_at"],
                    ))
                    proposals.update(corroborated_ai_proposals(row, evidence, remaining, extracted, _extractor_identity(extractor)))
                except Exception:
                    provider_failed = True
                    extras.append(_finding("provider_failed", "The configured extraction provider failed; retry is bounded across runs"))
            elif remaining and no_progress:
                extras.append(_finding("unchanged_evidence", "An earlier repair made no progress on this input; capture new evidence or review manually"))
            elif remaining and calls_for_input >= MAX_INPUT_ATTEMPTS:
                extras.append(_finding("retry_exhausted", "The extraction attempt budget for unchanged evidence is exhausted"))
            elif remaining and run["api_calls"] >= run["api_call_limit"]:
                extras.append(_finding("api_limit", "Provider-call limit reached; available deterministic repairs were still checked"))
            self._apply(run, item, row, fingerprint, proposals, extras, provider_failed)
        except Exception:
            with transaction() as con:
                self._complete_item(con, item, "failed", [_finding("inspection_failed", "Record inspection failed; original listing data was preserved")])

    def _reserve_call(self, run_id: str, item: dict) -> bool:
        with transaction() as con:
            changed = con.execute(
                """UPDATE attention_agent_runs SET api_calls=api_calls+1,updated_at=?
                   WHERE run_id=? AND status='running' AND owner_id=? AND api_calls<api_call_limit""",
                (now_iso(), run_id, self._owner_id),
            ).rowcount
            if changed:
                con.execute("UPDATE attention_agent_items SET api_called=api_called+1 WHERE item_id=? AND lease_token=?", (item["item_id"], item["lease_token"]))
            return bool(changed)

    def _apply(self, run: dict, item: dict, original: dict, fingerprint: str, proposals: dict, extras: list, provider_failed: bool) -> None:
        with transaction() as con:
            active = con.execute("SELECT * FROM attention_agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            claimed = con.execute("SELECT lease_token FROM attention_agent_items WHERE item_id=?", (item["item_id"],)).fetchone()
            if not active or active["owner_id"] != self._owner_id or not claimed or claimed["lease_token"] != item["lease_token"]:
                return
            if active["status"] != "running" or self._shutdown.is_set():
                con.execute("UPDATE attention_agent_items SET outcome='pending',lease_token=NULL WHERE item_id=?", (item["item_id"],))
                return
            record = con.execute("SELECT * FROM listings WHERE listing_id=?", (original["listing_id"],)).fetchone()
            current = dict(record) if record else None
            if not current or not self._eligible(con, current, json.loads(run["selection"])) or input_fingerprint(con, current) != fingerprint:
                self._complete_item(con, item, "skipped", [_finding("input_changed", "Record or evidence changed during inspection; no agent edit was applied")])
                return
            if self._external_busy(con):
                self._complete_item(con, item, "skipped", [_finding("worker_active", "Another capture or processing worker is active")])
                return
            candidate = dict(current)
            for field, proposal in proposals.items():
                candidate[field] = proposal["value"]
            invalid = {entry["field"] for entry in validate_fields(candidate)}
            changes: list[dict] = []
            for field, proposal in proposals.items():
                if field in invalid or current[field] == proposal["value"]:
                    continue
                changes.append({"field": field, "before": scrub_text(current[field]).text if isinstance(current[field], str) else current[field],
                                "after": proposal["value"], **{key: proposal[key] for key in ("evidence", "provider", "model", "prompt_version")}})
                # field is drawn exclusively from EXTRACTION_SCHEMA, never user SQL.
                con.execute(f"UPDATE listings SET {field}=? WHERE listing_id=?", (proposal["value"], current["listing_id"]))
                current[field] = proposal["value"]
                con.execute(
                    """INSERT INTO attention_agent_changes(change_id,run_id,item_id,listing_id,field,before_value,
                       after_value,evidence,provider,model,prompt_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), run["run_id"], item["item_id"], current["listing_id"], field,
                     _json(changes[-1]["before"]), _json(proposal["value"]), _json(proposal["evidence"]),
                     proposal["provider"], proposal["model"], proposal["prompt_version"], now_iso()),
                )
            signature = metadata_signature(current["platform"], current["title"], current["description"], current["price"])
            if changes or current["metadata_signature"] != signature:
                con.execute("UPDATE listings SET metadata_signature=?,updated_at=? WHERE listing_id=?", (signature, now_iso(), current["listing_id"]))
                current["metadata_signature"] = signature
            current_codes = {entry["code"] for entry in validate_fields(current)}
            for kind in FIELD_WARNING_TYPES - current_codes:
                con.execute("UPDATE warnings SET resolved=1 WHERE listing_id=? AND warning_type=? AND resolved=0", (current["listing_id"], kind))
            findings = inspect_listing(con, current)
            # Persist all current blockers without discarding original warnings.
            for finding in findings:
                if finding["code"] in FIELD_WARNING_TYPES and not con.execute(
                    "SELECT 1 FROM warnings WHERE listing_id=? AND warning_type=? AND message=? AND resolved=0",
                    (current["listing_id"], finding["code"], finding["message"]),
                ).fetchone():
                    con.execute(
                        "INSERT INTO warnings(warning_id,listing_id,warning_type,message,created_at) VALUES(?,?,?,?,?)",
                        (str(uuid.uuid4()), current["listing_id"], finding["code"], finding["message"], now_iso()),
                    )
            if current["status"] == "captured":
                for status in ("processing", "ai_extracted", "validating"):
                    transition(current["listing_id"], status, "attention agent targeted seller recovery extraction", con=con)
            if not findings:
                transition(current["listing_id"], "ready_for_review", "attention agent validation passed; final human review required", con=con)
            elif original["status"] == "captured":
                transition(current["listing_id"], "needs_attention", "attention agent recovered evidence inspected; blockers remain", con=con)
            final = dict(con.execute("SELECT * FROM listings WHERE listing_id=?", (current["listing_id"],)).fetchone())
            outcome = "failed" if provider_failed and not changes else _outcome(findings)
            self._complete_item(con, item, outcome, findings + extras if findings else [], changes, input_fingerprint(con, final))


attention_agent_manager = AttentionAgentManager()
