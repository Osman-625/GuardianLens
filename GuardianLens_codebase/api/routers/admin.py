from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from api.dependencies import get_repository, require_dev_admin
from api.schemas import AdminBundleSummary, AdminRecordSummary

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/login")
def development_admin_login(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, str]:
    del x_admin_token
    require_dev_admin(request)
    return {
        "status": "development_only",
        "message": "Replace this token gate with Supabase Auth before production-like use.",
    }


@router.get("/bundles", response_model=list[AdminBundleSummary])
def list_bundles(request: Request) -> list[AdminBundleSummary]:
    require_dev_admin(request)
    return [
        AdminBundleSummary(
            label="dev-stub-unvalidated",
            is_active=True,
            development_stub=True,
            component_versions={
                "visual": "contract-stub-v1",
                "textual": "contract-stub-v1",
                "behavioural": "contract-stub-v1",
                "fusion": "mean-stub-v1",
                "explanation": "template-stub-v1",
            },
            band_boundaries={"low_max": 33, "moderate_max": 66},
        )
    ]


@router.get("/records", response_model=list[AdminRecordSummary])
def list_records(request: Request) -> list[AdminRecordSummary]:
    require_dev_admin(request)
    return [
        AdminRecordSummary(
            assessment_id=record.id,
            title=record.title_scrubbed,
            band=record.result.band if record.result else None,
            score=record.result.score if record.result else None,
            status=record.status,
            created_at=record.created_at,
        )
        for record in get_repository(request).list_all_assessments()
    ]


@router.get("/export")
def export_records(
    request: Request,
    dataset: Literal["outputs", "study"] = "outputs",
) -> StreamingResponse:
    require_dev_admin(request)
    output = io.StringIO()
    writer = csv.writer(output)
    if dataset == "study":
        writer.writerow(["status", "message"])
        writer.writerow(
            ["empty", "Study rows are human-created only and are not generated in stub mode."]
        )
    else:
        writer.writerow(
            [
                "assessment_id",
                "title_scrubbed",
                "status",
                "score",
                "band",
                "model_bundle_label",
                "created_at",
            ]
        )
        for record in get_repository(request).list_all_assessments():
            writer.writerow(
                [
                    record.id,
                    record.title_scrubbed,
                    record.status.value,
                    record.result.score if record.result else "",
                    record.result.band.value if record.result else "",
                    record.result.model_bundle_label if record.result else "",
                    record.created_at.isoformat(),
                ]
            )
    content = output.getvalue().encode("utf-8")
    headers = {"Content-Disposition": f'attachment; filename="guardianlens-{dataset}.csv"'}
    return StreamingResponse(iter([content]), media_type="text/csv", headers=headers)
