from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlencode
from typing import Annotated, Literal
import uvicorn
from fastapi import FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from .config import settings, AI_PROVIDERS, get_active_provider, set_active_provider, provider_model, provider_configured
from .provider_info import MODEL_LISTERS
from .db import init_db, connect, transaction
from .security import (
    ensure_local_token,
    enforce_local_request,
    get_local_token,
    require_local_token,
    require_local_token_form,
    require_same_origin_asset,
    assert_safe_bind,
)
from .models import (
    CaptureRequest,
    SellerCaptureRequest,
    ReviewUpdate,
    BatchStartRequest,
    ReplayItemUpdate,
    SellerRetryPrepareRequest,
    SellerRetryItemUpdate,
)
from .capture import create_capture, attach_seller_capture
from .dashboard import (
    LISTING_STATUSES,
    RETRYABLE_FAILURE_STATUSES,
    REVIEW_QUEUE_STATUSES,
    adjacent_review_listing_ids,
    dashboard_snapshot,
    records_page,
    review_queue_snapshot,
)
from .batch import batch_manager
from .replay import (
    CSVImportError,
    create_csv_batch,
    create_manual_batch,
    get_stage_file,
    replay_manager,
)
from .seller_retry import seller_retry_manager
from .attention_agent import attention_agent_manager
from .review import (
    PrivateAssetCleanupError,
    get_listing,
    begin_review,
    edit_listing,
    edit_and_approve,
    action as review_action,
)
from .exports import export_approved
from .states import transition
from .errors import classify_error
from .collection_handoff import (
    get_annotation_dataset_status,
    refresh_annotation_dataset_safely,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_local_token()
    batch_manager.recover()
    replay_manager.recover()
    seller_retry_manager.recover()
    attention_agent_manager.recover()
    # The derived CSV dataset can take minutes to rebuild for a large collection.
    # Serve the dashboard while it refreshes, and finish publication on shutdown.
    dataset_refresh = asyncio.create_task(
        asyncio.to_thread(refresh_annotation_dataset_safely, "application_startup")
    )
    try:
        yield
    finally:
        attention_agent_manager.shutdown()
        seller_retry_manager.shutdown()
        replay_manager.shutdown()
        batch_manager.stop()
        await dataset_refresh

app = FastAPI(title="GuardianLens Data Collector", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=settings.root / "src" / "guardianlens" / "static"), name="static")
templates = Jinja2Templates(directory=settings.root / "src" / "guardianlens" / "templates")

@app.middleware("http")
async def local_security_boundary(request: Request, call_next):
    try:
        enforce_local_request(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response

@app.get("/health")
def health():
    return {"status":"ok","mode":settings.mode,"host":settings.host,"port":settings.port}

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    snapshot = dashboard_snapshot()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            **snapshot,
            "batch": batch_manager.status(),
            "replay": replay_manager.status(),
            "seller_retry": seller_retry_manager.status(),
            "attention": attention_agent_manager.status(),
            "annotation_dataset": get_annotation_dataset_status(),
            "token": get_local_token(),
            "mode": settings.mode,
            "csv_import_max_rows": settings.csv_import_max_rows,
            "ai_status": _ai_status_payload(),
        },
    )

@app.get("/api/dashboard/status")
def dashboard_status():
    return {
        **dashboard_snapshot(),
        "batch": batch_manager.status(),
        "replay": replay_manager.status(),
        "seller_retry": seller_retry_manager.status(),
        "annotation_dataset": get_annotation_dataset_status(),
        "ai_status": _ai_status_payload(),
    }

@app.post("/api/capture", dependencies=[Depends(require_local_token)])
def capture(payload: CaptureRequest):
    try:
        return create_capture(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/capture/{listing_id}/seller", dependencies=[Depends(require_local_token)])
def capture_seller(listing_id: str, payload: SellerCaptureRequest):
    try:
        return attach_seller_capture(listing_id, payload)
    except KeyError:
        raise HTTPException(404, "listing not found")
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/review", response_class=HTMLResponse)
def review_queue(request: Request, bucket: str | None = None, flash: str | None = None):
    try:
        queue = review_queue_snapshot(bucket=bucket)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return templates.TemplateResponse(
        request,
        "review_queue.html",
        {**queue, "token": get_local_token(), "flash": FLASH_LABELS.get(flash, flash)},
    )

@app.get("/api/review/queue")
def review_queue_status(bucket: str | None = None):
    try:
        return review_queue_snapshot(bucket=bucket)
    except ValueError as e:
        raise HTTPException(400, str(e))


FLASH_LABELS = {
    "approved": "Approved",
    "rejected": "Rejected",
    "skipped": "Skipped",
    "flagged": "Flagged",
    "saved": "Saved",
}


def _bucket_query_suffix(bucket: str | None) -> str:
    return f"?bucket={bucket}" if bucket and bucket != "all" else ""


def _review_url(path: str, bucket: str | None, *, flash: str | None = None) -> str:
    query: dict[str, str] = {}
    if bucket and bucket != "all":
        query["bucket"] = bucket
    if flash:
        query["flash"] = flash
    return f"{path}?{urlencode(query)}" if query else path


def _next_review_target(bucket: str | None, *, flash: str | None = None) -> str:
    """Where to send the operator after a terminal review action: the next item in
    the same bucket if one remains, otherwise back to that bucket's queue."""
    normalized = None if bucket in (None, "all") else bucket
    try:
        rows = review_queue_snapshot(limit=1, bucket=normalized)["rows"]
    except ValueError:
        return _review_url("/review", None, flash=flash)
    if rows:
        return _review_url(f"/review/{rows[0]['listing_id']}", bucket, flash=flash)
    return _review_url("/review", bucket, flash=flash)


def _review_response(
    request: Request,
    item: dict,
    *,
    bucket: str | None = None,
    flash: str | None = None,
    submitted: dict | None = None,
    error_message: str | None = None,
    status_code: int = 200,
):
    display_item = {**item, **(submitted or {})}
    try:
        adjacent = adjacent_review_listing_ids(item["listing_id"], bucket=None if bucket == "all" else bucket)
    except ValueError:
        adjacent = {"prev_id": None, "next_id": None}
    return templates.TemplateResponse(
        request,
        "review_detail.html",
        {
            "item": display_item,
            "categories": [x["name"] for x in settings.categories()],
            "token": get_local_token(),
            "review_active": item["status"] == "under_review",
            "error_message": error_message,
            "flash": FLASH_LABELS.get(flash, flash),
            "attention_history": attention_agent_manager.record_history(item["listing_id"]),
            "bucket": bucket,
            "prev_id": adjacent["prev_id"],
            "next_id": adjacent["next_id"],
        },
        status_code=status_code,
    )


def _record_response(
    request: Request,
    item: dict,
    *,
    bucket: str | None = None,
    page_notice: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "record_detail.html",
        {
            "item": item,
            "token": get_local_token(),
            "reviewable": item["status"] in REVIEW_QUEUE_STATUSES,
            "page_notice": page_notice,
            "attention_history": attention_agent_manager.record_history(item["listing_id"]),
            "bucket": bucket,
        },
        status_code=status_code,
    )


def _validation_message(error: ValidationError) -> str:
    details = []
    for item in error.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in item.get("loc", ())) or "field"
        details.append(f"{field}: {item.get('msg', 'invalid value')}")
    return "Check the submitted values. " + "; ".join(details[:6])


@app.get("/review/{listing_id}", response_class=HTMLResponse)
def review_detail(request: Request, listing_id: str, bucket: str | None = None, flash: str | None = None):
    try:
        item = get_listing(listing_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(404, str(e))
    if item["status"] not in REVIEW_QUEUE_STATUSES:
        raise HTTPException(409, "listing is not in the human review queue")
    return _review_response(request, item, bucket=bucket, flash=flash)

@app.post("/review/{listing_id}/begin", dependencies=[Depends(require_local_token_form)])
def review_begin(request: Request, listing_id: str, bucket: str | None = None):
    try:
        begin_review(listing_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        try:
            item = get_listing(listing_id)
        except KeyError:
            raise HTTPException(404, "listing not found")
        return _record_response(
            request,
            item,
            bucket=bucket,
            page_notice=f"Could not begin review: {exc}",
            status_code=409,
        )
    return RedirectResponse(f"/review/{listing_id}{_bucket_query_suffix(bucket)}", status_code=303)

@app.post("/review/{listing_id}/save", dependencies=[Depends(require_local_token_form)])
async def review_save(request: Request, listing_id: str, bucket: str | None = None):
    form = await request.form()
    submitted = {k: v for k, v in form.items() if k in ReviewUpdate.model_fields}
    non_empty = {k: v for k, v in submitted.items() if v != ""}
    try:
        validated = ReviewUpdate.model_validate(non_empty).model_dump(exclude_unset=True)
    except ValidationError as e:
        try:
            item = get_listing(listing_id)
        except KeyError:
            raise HTTPException(404, "listing not found")
        return _review_response(
            request,
            item,
            bucket=bucket,
            submitted=submitted,
            error_message=_validation_message(e),
            status_code=400,
        )
    # A field submitted empty is an explicit clear (-> NULL); one omitted from the form is untouched.
    data = {k: validated.get(k) for k in submitted}
    reason = str(form.get("reason") or "")[:2000] or None
    try:
        if form.get("submit_action") == "approve":
            edit_and_approve(listing_id, data, reason)
            return RedirectResponse(_next_review_target(bucket, flash="approved"), status_code=303)
        edit_listing(listing_id, data, reason)
    except ValueError as e:
        try:
            item = get_listing(listing_id)
        except KeyError:
            raise HTTPException(404, "listing not found")
        return _review_response(
            request,
            item,
            bucket=bucket,
            submitted=submitted,
            error_message=str(e),
            status_code=400,
        )
    except PrivateAssetCleanupError as e:
        return _record_response(
            request,
            get_listing(listing_id),
            bucket=bucket,
            page_notice=str(e),
            status_code=500,
        )
    return RedirectResponse(_review_url(f"/review/{listing_id}", bucket, flash="saved"), status_code=303)

@app.post("/review/{listing_id}/action/{target}", dependencies=[Depends(require_local_token_form)])
def act(request: Request, listing_id: str, target: str, bucket: str | None = None):
    try:
        review_action(listing_id,target)
    except ValueError as e:
        try:
            item = get_listing(listing_id)
        except KeyError:
            raise HTTPException(404, "listing not found")
        if item["status"] in REVIEW_QUEUE_STATUSES:
            return _review_response(request, item, bucket=bucket, error_message=str(e), status_code=400)
        return _record_response(request, item, bucket=bucket, page_notice=str(e), status_code=400)
    except PrivateAssetCleanupError as e:
        return _record_response(
            request,
            get_listing(listing_id),
            bucket=bucket,
            page_notice=str(e),
            status_code=500,
        )
    return RedirectResponse(_next_review_target(bucket, flash=target), status_code=303)

@app.get("/records", response_class=HTMLResponse)
def record_index(
    request: Request,
    status: str | None = None,
    platform: str | None = None,
    q: str | None = None,
    page: int = 1,
):
    try:
        result = records_page(status=status, platform=platform, query=q, page=page)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    def page_url(target_page: int) -> str:
        values = {
            key: value
            for key, value in {
                "status": result["filters"]["status"],
                "platform": result["filters"]["platform"],
                "q": result["filters"]["query"],
                "page": target_page,
            }.items()
            if value not in {"", None}
        }
        return f"/records?{urlencode(values)}"

    return templates.TemplateResponse(
        request,
        "records.html",
        {
            **result,
            "statuses": LISTING_STATUSES,
            "previous_url": page_url(result["page"] - 1) if result["page"] > 1 else None,
            "next_url": page_url(result["page"] + 1) if result["page"] < result["page_count"] else None,
        },
    )

@app.get("/records/{listing_id}", response_class=HTMLResponse)
def record_detail(request: Request, listing_id: str):
    try:
        item = get_listing(listing_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return _record_response(request, item)

@app.get("/asset/screenshot/{listing_id}")
def screenshot(request: Request, listing_id: str):
    require_same_origin_asset(request)
    c=connect(); row=c.execute("SELECT screenshot_path FROM listings WHERE listing_id=?",(listing_id,)).fetchone(); c.close()
    if not row or not row["screenshot_path"]: raise HTTPException(404)
    p=(settings.root/row["screenshot_path"]).resolve()
    allowed=(settings.data_dir/"private"/"screenshots").resolve()
    if allowed not in p.parents or not p.is_file(): raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control":"no-store, private","X-Content-Type-Options":"nosniff"})

@app.get("/asset/seller_screenshot/{listing_id}")
def seller_screenshot(request: Request, listing_id: str):
    require_same_origin_asset(request)
    c=connect(); row=c.execute("SELECT seller_screenshot_path FROM listings WHERE listing_id=?",(listing_id,)).fetchone(); c.close()
    if not row or not row["seller_screenshot_path"]: raise HTTPException(404)
    p=(settings.root/row["seller_screenshot_path"]).resolve()
    allowed=(settings.data_dir/"private"/"screenshots").resolve()
    if allowed not in p.parents or not p.is_file(): raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control":"no-store, private","X-Content-Type-Options":"nosniff"})

@app.get("/asset/image/{image_id}")
def image(request: Request, image_id: str):
    require_same_origin_asset(request)
    c=connect(); row=c.execute("SELECT storage_path FROM images WHERE image_id=?",(image_id,)).fetchone(); c.close()
    if not row: raise HTTPException(404)
    p=(settings.root/row["storage_path"]).resolve(); allowed=(settings.data_dir/"images").resolve()
    if allowed not in p.parents or not p.is_file(): raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})


@app.get("/asset/replay-stage/{batch_id}")
def replay_stage_file(request: Request, batch_id: str, download: bool = False):
    require_same_origin_asset(request)
    try:
        path = get_stage_file(batch_id)
    except KeyError:
        raise HTTPException(404, "replay batch not found")
    except FileNotFoundError:
        raise HTTPException(404, "Stage 1 URL file not found")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": f'{disposition}; filename="stage_1_urls_{path.parent.name}.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )

@app.post("/api/batch/start", dependencies=[Depends(require_local_token)])
def batch_start(payload: BatchStartRequest):
    _require_active_provider()
    try:
        rid = batch_manager.start(payload.duration_minutes, payload.item_limit)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"run_id":rid,"status":"running"}

@app.post("/api/batch/{command}", dependencies=[Depends(require_local_token)])
def batch_command(command: str):
    try:
        if command=="pause": batch_manager.pause()
        elif command=="resume": batch_manager.resume()
        elif command=="stop": batch_manager.stop()
        else: raise HTTPException(404,"unknown batch command")
    except RuntimeError as e: raise HTTPException(409,str(e))
    return batch_manager.status()

@app.get("/api/batch/status")
def batch_status(): return batch_manager.status()


@app.post("/api/replay/import", dependencies=[Depends(require_local_token)])
async def replay_import(
    file: UploadFile | None = File(default=None),
    manual_urls: str | None = Form(default=None),
    batch_name: str | None = Form(default=None),
):
    has_file = file is not None and bool(file.filename)
    has_manual = bool((manual_urls or "").strip())
    if has_file == has_manual:
        raise HTTPException(400, "Provide either one CSV file or pasted listing URLs.")
    try:
        if has_file:
            data = await file.read(settings.csv_import_max_bytes + 1)
            return create_csv_batch(data, file.filename or "upload.csv", batch_name)
        return create_manual_batch(manual_urls or "", batch_name)
    except CSVImportError as exc:
        raise HTTPException(400, str(exc))


def _require_active_provider() -> None:
    active_provider = get_active_provider()
    if not provider_configured(active_provider):
        raise HTTPException(
            409,
            f"{active_provider} is active but has no API key configured; configure or switch providers before starting",
        )


@app.post("/api/replay/{batch_id}/start", dependencies=[Depends(require_local_token)])
def replay_start(batch_id: str):
    try:
        return replay_manager.start(batch_id)
    except KeyError:
        raise HTTPException(404, "replay batch not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/replay/{batch_id}/command/{command}", dependencies=[Depends(require_local_token)])
def replay_command(batch_id: str, command: str):
    if command not in {"pause", "resume", "stop"}:
        raise HTTPException(404, "unknown replay batch command")
    try:
        return replay_manager.command(batch_id, command)
    except KeyError:
        raise HTTPException(404, "replay batch not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/replay/{batch_id}/retry-failed", dependencies=[Depends(require_local_token)])
def replay_retry_failed(batch_id: str):
    try:
        return replay_manager.retry_failed(batch_id)
    except KeyError:
        raise HTTPException(404, "replay batch not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/replay/status")
def replay_status(batch_id: str | None = None):
    return replay_manager.status(batch_id)


@app.post("/api/replay/claim", dependencies=[Depends(require_local_token)])
def replay_claim():
    return {"item": replay_manager.claim_next()}


@app.post("/api/replay/items/{batch_item_id}", dependencies=[Depends(require_local_token)])
def replay_item_update(batch_item_id: str, payload: ReplayItemUpdate):
    try:
        return replay_manager.update_item(
            batch_item_id,
            status=payload.status,
            status_message=payload.status_message,
            listing_id=payload.listing_id,
            error_type=payload.error_type,
            error_message=payload.error_message,
        )
    except KeyError:
        raise HTTPException(404, "replay item not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


class AttentionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["inspect", "repair"] = "inspect"
    listing_ids: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    ] | None = Field(default=None, min_length=1, max_length=10000)
    platform: Literal["carousell", "mudah"] | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=100)
    item_limit: int | None = Field(default=None, ge=1, le=10000, strict=True)
    time_limit_minutes: int = Field(default=60, ge=1, le=720, strict=True)
    api_call_limit: int = Field(default=25, ge=0, le=10000, strict=True)
    watch: bool = False
    recovery_batch_id: str | None = Field(default=None, min_length=1, max_length=64)


@app.post("/api/attention/start", dependencies=[Depends(require_local_token)])
def attention_start(payload: AttentionStartRequest):
    try:
        return attention_agent_manager.start(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post(
    "/api/attention/{run_id}/command/{command}",
    dependencies=[Depends(require_local_token)],
)
def attention_command(run_id: str, command: str):
    if command not in {"pause", "resume", "stop"}:
        raise HTTPException(404, "unknown attention agent command")
    try:
        return attention_agent_manager.command(run_id, command)
    except KeyError:
        raise HTTPException(404, "attention run not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/attention/status")
def attention_status(run_id: str | None = None):
    try:
        return attention_agent_manager.status(run_id)
    except KeyError:
        raise HTTPException(404, "attention run not found")


@app.post(
    "/api/attention/{run_id}/recover-sellers",
    dependencies=[Depends(require_local_token)],
)
def attention_recover_sellers(run_id: str):
    try:
        listing_ids = attention_agent_manager.recoverable_listing_ids(run_id)
        if not listing_ids:
            raise HTTPException(400, "no eligible seller captures remain in this run")
        prepared = seller_retry_manager.prepare(
            name="Attention agent seller recovery", listing_ids=listing_ids
        )
        batch = prepared.get("batch") or prepared
        return seller_retry_manager.start(batch["retry_batch_id"])
    except KeyError:
        raise HTTPException(404, "attention run or seller retry batch not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/attention/records/{listing_id}")
def attention_record_history(listing_id: str):
    try:
        return attention_agent_manager.record_history(listing_id)
    except KeyError:
        raise HTTPException(404, "listing not found")


@app.post("/api/seller-retry/prepare", dependencies=[Depends(require_local_token)])
def seller_retry_prepare(payload: SellerRetryPrepareRequest):
    try:
        return seller_retry_manager.prepare(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post(
    "/api/seller-retry/{retry_batch_id}/start",
    dependencies=[Depends(require_local_token)],
)
def seller_retry_start(retry_batch_id: str):
    try:
        return seller_retry_manager.start(retry_batch_id)
    except KeyError:
        raise HTTPException(404, "seller retry batch not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post(
    "/api/seller-retry/{retry_batch_id}/command/{command}",
    dependencies=[Depends(require_local_token)],
)
def seller_retry_command(retry_batch_id: str, command: str):
    if command not in {"pause", "resume", "stop"}:
        raise HTTPException(404, "unknown seller retry command")
    try:
        return seller_retry_manager.command(retry_batch_id, command)
    except KeyError:
        raise HTTPException(404, "seller retry batch not found")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/seller-retry/status")
def seller_retry_status(retry_batch_id: str | None = None):
    return seller_retry_manager.status(retry_batch_id)


@app.post("/api/seller-retry/claim", dependencies=[Depends(require_local_token)])
def seller_retry_claim():
    return {"item": seller_retry_manager.claim_next()}


@app.post(
    "/api/seller-retry/items/{retry_item_id}",
    dependencies=[Depends(require_local_token)],
)
def seller_retry_item_update(retry_item_id: str, payload: SellerRetryItemUpdate):
    try:
        return seller_retry_manager.update_item(
            retry_item_id,
            lease_token=payload.lease_token,
            status=payload.status,
            seller_url=payload.seller_url,
            status_message=payload.status_message,
            error_type=payload.error_type,
            error_message=payload.error_message,
        )
    except KeyError:
        raise HTTPException(404, "seller retry item not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))

class RetryListingsRequest(BaseModel):
    listing_ids: list[str]

@app.post("/api/queue/retry", dependencies=[Depends(require_local_token)])
def retry_listings(payload: RetryListingsRequest):
    listing_ids = list(dict.fromkeys(payload.listing_ids))
    if not listing_ids or len(listing_ids) > 100:
        raise HTTPException(400, "choose between 1 and 100 failed listings")
    retried: list[str] = []
    rejected: list[dict] = []
    with transaction() as con:
        control = con.execute(
            "SELECT command FROM processor_control WHERE control_id=1"
        ).fetchone()
        if control and control["command"] in {"running", "paused", "stopping"}:
            raise HTTPException(409, "finish the current processing run before retrying failures")
        for listing_id in listing_ids:
            row = con.execute("SELECT status FROM listings WHERE listing_id=?", (listing_id,)).fetchone()
            if not row:
                rejected.append({"listing_id": listing_id, "reason": "not_found"})
                continue
            if row["status"] not in RETRYABLE_FAILURE_STATUSES:
                rejected.append({"listing_id": listing_id, "reason": f"status_{row['status']}_not_retryable"})
                continue
            transition(listing_id, "captured", "human requested eligible retry", con=con)
            retried.append(listing_id)
    if retried:
        refresh_annotation_dataset_safely("queue_retry_committed")
    return {"retried": retried, "rejected": rejected}

def _ai_status_payload() -> dict:
    active = get_active_provider()
    return {
        "active": active,
        "providers": [
            {"name": name, "configured": provider_configured(name), "model": provider_model(name), "active": name == active}
            for name in AI_PROVIDERS
        ],
    }

@app.get("/api/ai/status")
def ai_status():
    return _ai_status_payload()

class SetProviderRequest(BaseModel):
    provider: str

@app.post("/api/ai/provider", dependencies=[Depends(require_local_token)])
def ai_set_provider(payload: SetProviderRequest):
    if payload.provider not in AI_PROVIDERS:
        raise HTTPException(400, f"unknown provider: {payload.provider!r}")
    if not provider_configured(payload.provider):
        raise HTTPException(400, f"{payload.provider} has no API key set in .env")
    set_active_provider(payload.provider)
    return _ai_status_payload()

@app.get("/api/ai/models/{provider}", dependencies=[Depends(require_local_token)])
def ai_list_models(provider: str):
    if provider not in AI_PROVIDERS:
        raise HTTPException(404, "unknown provider")
    if not provider_configured(provider):
        raise HTTPException(400, f"{provider} has no API key set in .env")
    try:
        models = MODEL_LISTERS[provider]()
    except Exception as e:
        classification = classify_error(e)
        raise HTTPException(502, f"{provider} model listing failed: {classification.user_message}")
    return {"provider": provider, "configured_model": provider_model(provider), "models": models}

@app.post("/api/export", dependencies=[Depends(require_local_token)])
def export():
    paths = export_approved()
    return {"files": [str(path.relative_to(settings.root)) for path in paths]}

def run():
    assert_safe_bind(settings.host)
    uvicorn.run("guardianlens.app:app", host=settings.host, port=settings.port, reload=False)
