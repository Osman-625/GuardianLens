export type RiskBand = "low" | "moderate" | "high";
export type PipelineStage = "visual" | "textual" | "behavioural" | "fusion" | "explanation";

export interface ApiError {
  error: {
    code: string;
    message: string;
    field: string | null;
  };
}

export interface SignalReason {
  feature_key: string;
  direction: "raises" | "lowers";
  display_text: string;
  rank: number;
}

export interface SignalCard {
  signal: "visual" | "textual" | "behavioural";
  probability: number | null;
  available: boolean;
  status_word: string;
  summary: string;
  reasons: SignalReason[];
  scope_note: string | null;
}

export interface AssessmentResult {
  assessment_id: string;
  title: string;
  score: number;
  band: RiskBand;
  signal_cards: SignalCard[];
  missing_data_notices: string[];
  suggested_checks: string[];
  disclaimer: string;
  model_bundle_label: string;
  created_at: string;
  total_latency_ms: number;
  development_stub: boolean;
}

export interface HistoryItem {
  assessment_id: string;
  title: string;
  score: number;
  band: RiskBand;
  created_at: string;
}
