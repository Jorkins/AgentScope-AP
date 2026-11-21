import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import { createServer } from 'vite';

const storage = new Map([
	['server_url', 'http://localhost:8000'],
	['username', 'alice'],
	['ap_token', 'test-jwt-token'],
]);
globalThis.localStorage = {
	getItem: (key) => storage.get(key) ?? null,
	setItem: (key, value) => storage.set(key, String(value)),
	removeItem: (key) => storage.delete(key),
};

const requests = [];
globalThis.fetch = async (url, options) => {
	requests.push({ url: String(url), options });
	return new Response(
		JSON.stringify({
			name: 'skill-a',
			display_name: 'Skill A',
			installed_enabled: true,
			enabled: true,
		}),
		{ status: 200, headers: { 'Content-Type': 'application/json' } },
	);
};

const vite = await createServer({
	root: fileURLToPath(new URL('..', import.meta.url)),
	configFile: false,
	appType: 'custom',
	logLevel: 'silent',
	server: { middlewareMode: true },
});

try {
	const { agentApi } = await vite.ssrLoadModule('/src/api/agent.ts');
	await agentApi.listToolBindings('agent/1');
	await agentApi.updateToolBinding('agent/1', {
		kind: 'skill',
		resource_name: 'skill-a',
		enabled: true,
	});

	assert.equal(requests.length, 2);
	for (const request of requests) {
		assert.equal(
			request.url,
			'http://localhost:8000/api/platform/agents/agent%2F1/tool-bindings',
		);
		assert.equal(request.options.headers.Authorization, 'Bearer test-jwt-token');
	}
	assert.equal(requests[0].options.method, 'GET');
	assert.equal(requests[1].options.method, 'PUT');
	assert.deepEqual(JSON.parse(requests[1].options.body), {
		kind: 'skill',
		resource_name: 'skill-a',
		enabled: true,
	});
	console.log('tool bindings api: 1 passed');
} finally {
	await vite.close();
}
