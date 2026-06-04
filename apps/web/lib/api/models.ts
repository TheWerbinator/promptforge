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
