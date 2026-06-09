import type { components } from "./schema";

/** Convenience aliases over the generated OpenAPI schema. */
export type Prompt = components["schemas"]["PromptResponse"];
export type PromptDetail = components["schemas"]["PromptDetailResponse"];
export type PromptList = components["schemas"]["PromptListResponse"];
export type PromptVersion = components["schemas"]["PromptVersionResponse"];
export type PromptVisibility = components["schemas"]["PromptVisibility"];

/** A declared prompt variable (the shape stored in PromptVersion.variables). */
export interface PromptVar {
  name: string;
  type: string;
}

export const VARIABLE_TYPES = ["str", "int", "float", "bool"] as const;
export const VISIBILITIES: PromptVisibility[] = ["private", "org", "public"];

export type EvalSuite = components["schemas"]["EvalSuiteResponse"];
export type EvalCase = components["schemas"]["EvalCaseResponse"];
export type EvalBatch = components["schemas"]["EvalBatchResponse"];
export type EvalBatchDetail = components["schemas"]["EvalBatchDetailResponse"];
export type EvalResult = components["schemas"]["EvalResultResponse"];
export type JudgeKind = components["schemas"]["JudgeKind"];
export type Run = components["schemas"]["RunResponse"];

/** GET /api/v1/runs wrapper (defined here; added to the API after schema gen). */
export interface RunList {
  items: Run[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export const JUDGE_KINDS: JudgeKind[] = ["exact", "contains", "regex", "llm_judge"];

/** Shape of the small JSON payload in each SSE `result` event (see eval_runner). */
export interface BatchProgressEvent {
  kind: string;
  case_id: string;
  version_id: string;
  score: number;
  passed: boolean;
  completed: number;
  total: number;
}

// ----- ragent (separate service; hand-typed — no web schema-gen for ragent yet) -----

export interface Corpus {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  embedding_model: string;
  document_count: number;
}

export interface RagentDocument {
  id: string;
  title: string;
  content_type: string;
  status: string;
  byte_size: number;
  error: string | null;
}

/** A source the agent cited (from the cite_sources tool). Rendered loosely. */
export interface Citation {
  chunk_id?: string;
  document_title?: string;
  ordinal?: number;
  snippet?: string;
  [key: string]: unknown;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}
