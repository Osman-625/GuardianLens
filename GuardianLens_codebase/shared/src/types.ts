// Shared type definitions: the shapes the FastAPI service sends and receives, plus the
// small "capture metadata" record the extension attaches to a submission.
// Used by the website, the extension, and the API client. They mirror api/schemas.py, so a field
// that changes there must change here too.

/** The three risk bands the fused score maps to. */
export type RiskBand = "low" | "moderate" | "high";

/** The five processing stages, in the order the API reports them. */
export type PipelineStage = "visual" | "textual" | "behavioural" | "fusion" | "explanation";

/** The three independent signals shown as cards. */
export type SignalName = "visual" | "textual" | "behavioural";

/** Lifecycle of one assessment on the server. */
export type AssessmentStatus = "processing" | "complete" | "failed" | "abandoned";

/** What a buyer can say about a result. */
export type FeedbackVerdict = "helpful" | "unclear" | "potentially_incorrect";

/** The two marketplaces GuardianLens supports. */
export type Platform = "mudah" | "carousell";

/**
 * The exact hosts a listing page can be served from. The API accepts only these values in
 * capture metadata, so a listing URL can never be smuggled in through that field.
 */
export type PlatformHost =
  "mudah.my" | "www.mudah.my" | "carousell.com.my" | "www.carousell.com.my";

/** The JSON body of every error response: `{ "error": { code, message, field } }`. */
export interface ApiError {
  error: {
    /** Stable machine-readable code, for example "invalid_price". */
    code: string;
    /** Plain-language message that is safe to show to a buyer. */
    message: string;
    /** The form field the error belongs to, or null when it is not about one field. */
    field: string | null;
  };
}

/** One plain-language reason behind a signal's status (top reasons only). */
export interface SignalReason {
  feature_key: string;
  /** Whether this reason pushed the risk up or down. */
  direction: "raises" | "lowers";
  display_text: string;
  rank: number;
}

/** One of the three signal cards on a result. */
export interface SignalCard {
  signal: SignalName;
  /** Null when the signal could not be computed (unavailable). */
  probability: number | null;
  /** False means the signal is "unknown", never "safe" and never "suspicious". */
  available: boolean;
  status_word: string;
  summary: string;
  reasons: SignalReason[];
  /** Extra wording that limits what the signal proves (for example corpus scope). */
  scope_note: string | null;
}

/** A finished assessment, as returned by GET /api/v1/assess/{id}/result. */
export interface AssessmentResult {
  assessment_id: string;
  title: string;
  /** Integer from 0 to 100; 100 is the lowest estimated risk. Never shown with decimals. */
  score: number;
  band: RiskBand;
  signal_cards: SignalCard[];
  missing_data_notices: string[];
  suggested_checks: string[];
  /** Must be shown wherever the score is shown. */
  disclaimer: string;
  model_bundle_label: string;
  created_at: string;
  total_latency_ms: number;
  /** True while the scores come from development stubs, not trained models. */
  development_stub: boolean;
}

/** One row of the session history list. */
export interface HistoryItem {
  assessment_id: string;
  title: string;
  score: number;
  band: RiskBand;
  created_at: string;
}

/** Progress of a running assessment, polled while the buyer waits. */
export interface AssessmentStatusResponse {
  status: AssessmentStatus;
  /** The stage currently running, or null when none is. */
  stage: PipelineStage | null;
  message: string | null;
}

/** Response of POST /api/v1/session: the opaque token a header-transport client stores. */
export interface SessionCreated {
  session_token: string;
}

/** Body of POST /api/v1/assess/{id}/feedback. */
export interface FeedbackRequest {
  verdict: FeedbackVerdict;
  comment: string | null;
}

/** The fields whose origin the extension reports in capture metadata. */
export type CaptureFieldName =
  | "title"
  | "description"
  | "price"
  | "category"
  | "platform"
  | "images"
  | "account_age_days"
  | "rating"
  | "review_count"
  | "active_listing_count";

/**
 * Where a submitted value came from: read from the page, changed by the buyer after
 * capture, or not found on the page (so the buyer typed it or left it blank).
 */
export type CaptureFieldStatus = "captured" | "edited" | "not_found";

/**
 * Metadata sent with an extension submission (form field `capture_meta`, JSON string).
 * It is stored for evaluation only and never feeds the score. It deliberately holds the
 * platform host and per-field status, and never the listing URL.
 */
export interface CaptureMetaPayload {
  /** Version of the extraction code that produced the capture. */
  adapter_version: string;
  platform_host: PlatformHost;
  fields: Record<CaptureFieldName, CaptureFieldStatus>;
}
