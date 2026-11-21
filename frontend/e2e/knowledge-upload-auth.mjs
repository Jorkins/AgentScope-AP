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

let request;
class FakeXMLHttpRequest {
	constructor() {
		this.upload = {};
		this.headers = {};
		this.status = 0;
		this.statusText = '';
		this.responseText = '';
	}

	open(method, url, async) {
		this.method = method;
		this.url = url;
		this.async = async;
	}

	setRequestHeader(name, value) {
		this.headers[name] = value;
	}

	send(body) {
		this.body = body;
		request = this;
		this.status = 200;
		this.responseText = '{}';
		this.onload?.();
	}

	abort() {
		this.onabort?.();
	}
}
globalThis.XMLHttpRequest = FakeXMLHttpRequest;

const vite = await createServer({
	root: fileURLToPath(new URL('..', import.meta.url)),
	configFile: false,
	appType: 'custom',
	logLevel: 'silent',
	server: { middlewareMode: true },
});

try {
	const { knowledgeBaseApi } = await vite.ssrLoadModule('/src/api/knowledgeBase.ts');
	await knowledgeBaseApi.uploadDocument(
		'kb-1',
		new File(['knowledge'], 'knowledge.txt', { type: 'text/plain' }),
	);

	assert.equal(request.headers['X-User-ID'], 'alice');
	assert.equal(request.headers.Authorization, 'Bearer test-jwt-token');
	assert.equal(request.method, 'POST');
	assert.equal(request.url, 'http://localhost:8000/knowledge_bases/kb-1/documents');

	const { workspaceApi } = await vite.ssrLoadModule('/src/api/workspace.ts');
	await workspaceApi.skill.upload(
		'agent-1',
		'session-1',
		[new File(['skill'], 'SKILL.md', { type: 'text/markdown' })],
	);

	assert.equal(request.headers['X-User-ID'], 'alice');
	assert.equal(request.headers.Authorization, 'Bearer test-jwt-token');
	assert.equal(request.method, 'POST');
	assert.equal(
		request.url,
		'http://localhost:8000/workspace/skill/upload?agent_id=agent-1&session_id=session-1',
	);
	console.log('knowledge and skill upload auth: 2 passed');
} finally {
	await vite.close();
}
