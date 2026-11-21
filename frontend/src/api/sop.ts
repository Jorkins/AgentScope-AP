import { client } from './client';
import type { ChatModelConfig, RecordBase } from './types';

/** Where a step, or a whole run, stands (mirrors agentscope SOPPhase). */
export type SOPPhase = 'pending' | 'running' | 'awaiting' | 'completed' | 'failed';

export interface SOPAgentRef {
	agent_id: string;
	session_key: string;
}

export interface SOPHumanVerifier {
	type: 'human';
	question: string;
}

export interface SOPAgentVerifier {
	type: 'agent';
	agent: SOPAgentRef;
	criteria: string;
}

export type SOPVerifier = SOPHumanVerifier | SOPAgentVerifier;

export interface SOPStepData {
	version?: 'v1';
	/** A brief, actionable name. */
	subject: string;
	/** What this step must achieve. */
	description: string;
	executor: SOPAgentRef;
	/** `null` accepts whatever the executor returns. */
	verifier: SOPVerifier | null;
	max_attempts?: number;
}

export interface SOPSessionSettings {
	chat_model_config: ChatModelConfig;
	fallback_chat_model_config?: ChatModelConfig | null;
}

export interface SOPData {
	name: string;
	description: string;
	steps: SOPStepData[];
	workspace_grain?: string;
	/** Keyed by session_key; every key named by a step must be configured. */
	session_settings: Record<string, SOPSessionSettings>;
}

export interface SOPRecord extends RecordBase {
	user_id: string;
	data: SOPData;
}

export interface ListSOPsResponse {
	sops: SOPRecord[];
	total: number;
}

export interface VerificationResult {
	passed: boolean;
	message: string;
	verifier: string;
	created_at: string;
}

export interface SOPStepRunState {
	phase: SOPPhase;
	submission?: Array<{ type: string; text?: string }> | null;
	verifications: VerificationResult[];
}

export interface SOPRunState {
	id: string;
	steps: SOPStepRunState[];
	created_at: string;
	phase: SOPPhase;
}

export interface SOPRunRecord extends RecordBase {
	user_id: string;
	sop_id: string;
	/** Copy of the procedure at start — later edits do not affect the run. */
	definition: SOPData;
	/** session_key → session id opened for this run. */
	sessions: Record<string, string>;
	state: SOPRunState;
}

export interface ListSOPRunsResponse {
	runs: SOPRunRecord[];
	total: number;
}

export interface SubmitVerdictRequest {
	step_index: number;
	passed: boolean;
	message?: string;
}

export const sopApi = {
	list: () => client.get<ListSOPsResponse>('/sop/'),

	get: (sopId: string) => client.get<SOPRecord>(`/sop/${sopId}`),

	create: (data: SOPData) => client.post<{ sop_id: string }>('/sop/', { data }),

	update: (sopId: string, data: SOPData) =>
		client.patch<SOPRecord>(`/sop/${sopId}`, { data }),

	delete: (sopId: string) => client.delete(`/sop/${sopId}`),

	listRuns: (sopId?: string, phase?: SOPPhase) =>
		client.get<ListSOPRunsResponse>('/sop/runs', {
			...(sopId ? { sop_id: sopId } : {}),
			...(phase ? { phase } : {}),
		}),

	getRun: (runId: string, options?: { silent?: boolean }) =>
		client.get<SOPRunRecord>(`/sop/runs/${runId}`, undefined, options),

	startRun: (sopId: string) => client.post<SOPRunRecord>(`/sop/${sopId}/runs`, { inputs: [] }),

	deleteRun: (runId: string) => client.delete(`/sop/runs/${runId}`),

	submitVerdict: (runId: string, body: SubmitVerdictRequest) =>
		client.post<SOPRunRecord>(`/sop/runs/${runId}/verdict`, body),
};
