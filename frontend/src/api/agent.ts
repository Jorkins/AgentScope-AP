import { client } from './client';
import type {
	AgentListResponse,
	AgentToolBinding,
	AgentToolBindingList,
	AgentView,
	AgentSchemaV2Response,
	CreateAgentRequest,
	CreateAgentResponse,
	UpdateAgentRequest,
	UpdateAgentToolBindingRequest,
} from './types';

export const agentApi = {
	list: () => client.get<AgentListResponse>('/agent/'),

	getSchema: () => client.get<AgentSchemaV2Response>('/agent/schema/v2'),

	create: (body: CreateAgentRequest, options?: { silent?: boolean }) =>
		client.post<CreateAgentResponse>('/agent/', body, undefined, options),

	update: (agentId: string, body: UpdateAgentRequest, options?: { silent?: boolean }) =>
		client.patch<AgentView>(`/agent/${agentId}`, body, undefined, options),

	delete: (agentId: string) => client.delete(`/agent/${agentId}`),

	listToolBindings: (agentId: string) =>
		client.get<AgentToolBindingList>(
			`/api/platform/agents/${encodeURIComponent(agentId)}/tool-bindings`,
		),

	updateToolBinding: (agentId: string, body: UpdateAgentToolBindingRequest) =>
		client.put<AgentToolBinding>(
			`/api/platform/agents/${encodeURIComponent(agentId)}/tool-bindings`,
			body,
			{ silent: true },
		),
};
