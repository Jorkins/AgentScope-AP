import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';
import { createServer } from 'vite';

const root = fileURLToPath(new URL('..', import.meta.url));
const origin = 'http://127.0.0.1:5174';
const vite = await createServer({
	root,
	server: { host: '127.0.0.1', port: 5174, strictPort: true },
});
let browser;

try {
	await vite.listen();
	browser = await chromium.launch({ headless: true });
	const page = await browser.newPage({ locale: 'zh-CN' });
	page.setDefaultTimeout(5000);
	const updates = [];
	const agent = {
		id: 'shared-agent',
		user_id: 'owner',
		source: 'user',
		editable: false,
		created_at: '2026-01-01T00:00:00Z',
		updated_at: '2026-01-01T00:00:00Z',
		data: {
			id: 'shared-agent',
			name: 'Shared Agent',
			system_prompt: '',
			chat_config: { context_config: {}, react_config: {}, invite_config: {} },
		},
	};
	const binding = {
		name: 'skill-a',
		display_name: 'Alice Skill',
		installed_enabled: true,
		enabled: false,
	};

	await page.addInitScript(
		({ serverUrl }) => {
			localStorage.setItem('server_url', serverUrl);
			localStorage.setItem('username', 'alice');
			localStorage.setItem('ap_token', 'test-jwt-token');
			localStorage.setItem('i18nextLng', 'zh');
		},
		{ serverUrl: origin },
	);
	await page.route('**/*', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (url.origin !== origin) return route.continue();
		const path = url.pathname;
		const json = (body, status = 200) =>
			route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

		if (path === '/agent/') return json({ agents: [agent], total: 1 });
		if (path === '/agent/schema/v2') return json({});
		if (path === '/sessions/') return json({ sessions: [], total: 0 });
		if (['/skill', '/hub/skill', '/mcp', '/hub/mcp'].includes(path)) return json([]);
		if (path === '/api/platform/agents/shared-agent/tool-bindings') {
			if (request.method() === 'PUT') {
				const update = request.postDataJSON();
				updates.push(update);
				return json({
					...binding,
					name: update.resource_name,
					display_name: update.kind === 'skill' ? 'Alice Skill' : 'Alice MCP',
					enabled: update.enabled,
				});
			}
			return json({
				skills: [binding],
				mcps: [{ ...binding, name: 'mcp-a', display_name: 'Alice MCP' }],
			});
		}
		if (path.startsWith('/hub/') || path.startsWith('/api/')) return json({});
		return route.continue();
	});

	await page.goto(`${origin}/skill/bindings`, {
		waitUntil: 'domcontentloaded',
		timeout: 30000,
	});
	await page.getByRole('button', { name: 'Agent 绑定', exact: true }).waitFor();
	await page.getByRole('heading', { name: 'Agent 绑定', exact: true }).waitFor();
	await page.getByText('Shared Agent', { exact: true }).first().waitFor();
	const toggle = page.getByRole('switch', { name: '绑定 Alice Skill' });
	await toggle.waitFor();
	assert.equal(await toggle.getAttribute('aria-checked'), 'false');
	await toggle.click();
	await page.waitForFunction(() => {
		const element = document.querySelector('[role="switch"][aria-label="绑定 Alice Skill"]');
		return element?.getAttribute('aria-checked') === 'true';
	});
	assert.deepEqual(updates, [
		{ kind: 'skill', resource_name: 'skill-a', enabled: true },
	]);
	assert.equal(await page.getByText('Alice MCP', { exact: true }).count(), 0);

	await page.goto(`${origin}/mcp/bindings`, {
		waitUntil: 'domcontentloaded',
		timeout: 30000,
	});
	await page.getByRole('button', { name: 'Agent 绑定', exact: true }).waitFor();
	await page.getByRole('heading', { name: 'Agent 绑定', exact: true }).waitFor();
	await page.getByText('Shared Agent', { exact: true }).first().waitFor();
	const mcpToggle = page.getByRole('switch', { name: '绑定 Alice MCP' });
	await mcpToggle.waitFor();
	assert.equal(await mcpToggle.getAttribute('aria-checked'), 'false');
	await mcpToggle.click();
	await page.waitForFunction(() => {
		const element = document.querySelector('[role="switch"][aria-label="绑定 Alice MCP"]');
		return element?.getAttribute('aria-checked') === 'true';
	});
	assert.deepEqual(updates, [
		{ kind: 'skill', resource_name: 'skill-a', enabled: true },
		{ kind: 'mcp', resource_name: 'mcp-a', enabled: true },
	]);
	assert.equal(await page.getByText('Alice Skill', { exact: true }).count(), 0);

	await page.goto(`${origin}/chat/shared-agent`, {
		waitUntil: 'domcontentloaded',
		timeout: 30000,
	});
	const agentMenu = page.locator('button:has(svg.lucide-ellipsis)').first();
	await agentMenu.waitFor();
	assert.equal(await agentMenu.isDisabled(), false);
	await agentMenu.click();
	const bindingsItem = page.getByRole('menuitem', { name: 'Skill/MCP 绑定', exact: true });
	await bindingsItem.waitFor();
	assert.equal(await page.getByRole('menuitem', { name: '设置', exact: true }).count(), 0);
	assert.equal(await page.getByRole('menuitem', { name: '删除智能体', exact: true }).count(), 0);
	await bindingsItem.click();
	const dialog = page.getByRole('dialog');
	await dialog.waitFor();
	await dialog.getByRole('heading', { name: 'Agent 绑定', exact: true }).waitFor();
	await dialog.getByRole('switch', { name: '绑定 Alice Skill' }).waitFor();
	await dialog.getByRole('switch', { name: '绑定 Alice MCP' }).waitFor();
	console.log('tool bindings ui: 3 passed');
} finally {
	await browser?.close();
	await vite.close();
}
