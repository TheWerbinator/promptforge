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
