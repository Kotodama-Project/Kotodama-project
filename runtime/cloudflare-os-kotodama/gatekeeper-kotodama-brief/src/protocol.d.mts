export type Brief = { objective: string; deliverable: string; constraints: string[]; acceptance_criteria: string[]; open_questions: string[] };
export type Result = { request_id: string; state: "running" | "ready" | "failed" | "interrupted"; brief: Brief | null; task_state_changed: false; publication: false };
export function validateBrief(value: unknown): Brief;
export function validateAdmission(value: unknown): { allowed: true; binding_sha256: string };
export function validateSource(value: unknown): { handoff_id: string; revision: number; overview: string; binding_sha256: string };
export function validateQueued(value: unknown, requestId: string): { request_id: string; state: Result["state"]; task_state_changed: false };
export function validateResult(value: unknown, requestId: string): Result;
export function validateRevoked(value: unknown): { revoked: true };
