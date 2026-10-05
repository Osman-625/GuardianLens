// Frontend type entry point. The definitions now live in @guardianlens/shared so the website
// and the extension cannot drift apart; this file only re-exports the ones the pages use,
// which keeps the existing `@/lib/types` imports working.
export type {
  ApiError,
  AssessmentResult,
  HistoryItem,
  PipelineStage,
  RiskBand,
  SignalCard,
  SignalReason,
} from "@guardianlens/shared";
