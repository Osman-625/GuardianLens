// Frontend type entry point. The definitions live in @guardianlens/shared so the website and the
// extension use one set; this file re-exports the ones the pages need, so pages import them from
// `@/lib/types`.
export type {
  AssessmentResult,
  HistoryItem,
  PipelineStage,
  RiskBand,
  SignalCard,
  SignalReason,
} from "@guardianlens/shared";
