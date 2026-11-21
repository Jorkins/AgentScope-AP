import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const frontendRoot = fileURLToPath(new URL('..', import.meta.url));
const backendRoot = resolve(frontendRoot, '../backend');
const apiOrigin = process.env.AP_API_ORIGIN ?? 'http://127.0.0.1:8000';
const webOrigin = process.env.AP_WEB_ORIGIN ?? 'http://127.0.0.1:5173';
const runId = Date.now().toString(36);
const password = `P48!${runId}pass`;
const alice = { username: `p48a${runId}`, token: '' };
const bob = { username: `p48b${runId}`, token: '' };
const agentName = `P4-8 Shared ${runId}`;
const aliceSkill = `p48-skill-a-${runId}`;
const bobSkill = `p48-skill-b-${runId}`;
const aliceSkillDisplay = `Alice Skill ${runId}`;
const bobSkillDisplay = `Bob Skill ${runId}`;
const aliceMcp = `p48-mcp-a-${runId}`;
const bobMcp = `p48-mcp-b-${runId}`;
let passed = 0;

function ok(label) {
	passed += 1;
	console.log(`PASS ${String(passed).padStart(2, '0')} ${label}`);
}

function withQuery(path, params) {
	const url = new URL(path, apiOrigin);
	for (const [key, value] of Object.entries(params ?? {})) {
		url.searchParams.set(key, value);
	}
	return `${url.pathname}${url.search}`;
}

async function request(user, path, { method = 'GET', body, form } = {}) {
	const headers = {};
	if (user) {
		headers['X-User-ID'] = user.username;
		if (user.token) headers.Authorization = `Bearer ${user.token}`;
	}
	if (body !== undefined) headers['Content-Type'] = 'application/json';
	const response = await fetch(new URL(path, apiOrigin), {
		method,
		headers,
		body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
	});
	const text = await response.text();
	let data = null;
	if (text) {
		try {
			data = JSON.parse(text);
		} catch {
			data = text;
		}
	}
	return { status: response.status, data, text };
}

async function api(user, path, options = {}, expected = [200, 201, 204]) {
	const response = await request(user, path, options);
	assert.ok(
		expected.includes(response.status),
		`${options.method ?? 'GET'} ${path} -> ${response.status}: ${response.text}`,
	);
	return response.data;
}

async function register(user) {
	const result = await api(null, '/api/platform/auth/register', {
		method: 'POST',
		body: {
			username: user.username,
			password,
			display_name: user.username,
		},
	});
	user.token = result.access_token;
}

async function installSkill(user, agentId, sessionId, skillName) {
	const markdown = `---\nname: ${skillName}\ndescription: P4-8 live acceptance skill\n---\n\n# ${skillName}\n`;
	const form = new FormData();
	form.append(
		'manifest',
		JSON.stringify({
			entries: [{ path: `${skillName}/SKILL.md`, size: Buffer.byteLength(markdown) }],
		}),
	);
	form.append('files', new Blob([markdown], { type: 'text/markdown' }), 'SKILL.md');
	await api(
		user,
		withQuery('/workspace/skill/upload', { agent_id: agentId, session_id: sessionId }),
		{ method: 'POST', form },
	);
}

async function installMcp(user, agentId, sessionId, name) {
	await api(
		user,
		withQuery('/workspace/mcp', { agent_id: agentId, session_id: sessionId }),
		{
			method: 'POST',
			body: {
				name,
				is_stateful: false,
				mcp_config: { type: 'http_mcp', url: 'http://127.0.0.1:1/mcp' },
			},
		},
	);
}

async function workspaceStatus(user, agentId, sessionId) {
	return api(
		user,
		withQuery('/workspace/status', { agent_id: agentId, session_id: sessionId }),
	);
}

async function directoryListing(user, agentId, sessionId, path = '') {
	return api(
		user,
		withQuery('/workspace/directories', {
			agent_id: agentId,
			session_id: sessionId,
			path,
		}),
	);
}

async function runtimeSkills(user, agentId, sessionId) {
	return api(
		user,
		withQuery('/workspace/skill', { agent_id: agentId, session_id: sessionId }),
	);
}

async function runtimeMcps(user, agentId, sessionId) {
	return api(
		user,
		withQuery('/workspace/mcp', { agent_id: agentId, session_id: sessionId }),
	);
}

function seedSkillRecords() {
	execFileSync(
		resolve(backendRoot, '.venv/Scripts/python.exe'),
		[
			resolve(backendRoot, 'tests/live_p4_8_seed.py'),
			alice.username,
			aliceSkill,
			aliceSkillDisplay,
			bob.username,
			bobSkill,
			bobSkillDisplay,
		],
		{
			env: { ...process.env, PYTHONPATH: backendRoot },
			stdio: 'inherit',
		},
	);
}

async function login(page, user) {
	await page.goto(webOrigin, { waitUntil: 'domcontentloaded' });
	await page.locator('#server').fill(apiOrigin);
	await page.locator('#login-username').fill(user.username);
	await page.locator('#login-password').fill(password);
	await page.getByRole('button', { name: '登录', exact: true }).click();
	await page.waitForFunction(() => Boolean(localStorage.getItem('ap_token')));
	assert.equal(
		await page.evaluate(() => localStorage.getItem('username')),
		user.username,
	);
}

async function toggleResource(page, path, displayName) {
	await page.goto(`${webOrigin}${path}`, { waitUntil: 'domcontentloaded' });
	const toggle = page.getByRole('switch', {
		name: `绑定 ${displayName}`,
		exact: true,
	});
	await toggle.waitFor({ state: 'visible', timeout: 15000 });
	assert.equal(await toggle.getAttribute('aria-checked'), 'false');
	await toggle.click();
	await page.waitForFunction(
		(name) =>
			document
				.querySelector(`[role="switch"][aria-label="${name}"]`)
				?.getAttribute('aria-checked') === 'true',
		`绑定 ${displayName}`,
	);
}

let browser;
const contexts = [];
const pages = [];
const browserErrors = [];

try {
	await register(alice);
	await register(bob);
	ok('两个独立验收用户通过真实 API 注册');

	const { agent_id: agentId } = await api(alice, '/agent/', {
		method: 'POST',
		body: { name: agentName, system_prompt: 'P4-8 isolation acceptance' },
	});
	await api(alice, '/api/platform/shares', {
		method: 'POST',
		body: {
			kind: 'agent',
			owner_id: alice.username,
			resource_id: agentId,
			permission: 'read',
			grantee_user_id: bob.username,
		},
	});
	const bobAgents = await api(bob, '/agent/');
	const shared = bobAgents.agents.find((agent) => agent.id === agentId);
	assert.equal(shared?.data.name, agentName);
	assert.equal(shared?.editable, false);
	assert.equal(shared?.user_id, alice.username);
	ok('Bob 可见 Alice 的只读共享 Agent');

	const { session_id: aliceSession } = await api(alice, '/sessions/', {
		method: 'POST',
		body: { agent_id: agentId },
	});
	const { session_id: bobSession } = await api(bob, '/sessions/', {
		method: 'POST',
		body: { agent_id: agentId },
	});
	const aliceStatus = await workspaceStatus(alice, agentId, aliceSession);
	const bobStatus = await workspaceStatus(bob, agentId, bobSession);
	const aliceWorkspace = basename(aliceStatus.workdir);
	const bobWorkspace = basename(bobStatus.workdir);
	assert.notEqual(aliceWorkspace, bobWorkspace);
	assert.notEqual(aliceStatus.workdir, bobStatus.workdir);
	ok('共享 Agent 的两个用户获得不同 workspace_id 与目录');

	await installSkill(alice, agentId, aliceSession, aliceSkill);
	await installSkill(bob, agentId, bobSession, bobSkill);
	await installMcp(alice, agentId, aliceSession, aliceMcp);
	await installMcp(bob, agentId, bobSession, bobMcp);
	seedSkillRecords();
	assert.deepEqual(await runtimeSkills(alice, agentId, aliceSession), []);
	assert.deepEqual(await runtimeSkills(bob, agentId, bobSession), []);
	assert.deepEqual(await runtimeMcps(alice, agentId, aliceSession), []);
	assert.deepEqual(await runtimeMcps(bob, agentId, bobSession), []);
	ok('Skill/MCP 已真实安装，但绑定前运行时白名单均为空');

	await writeFile(`${aliceStatus.workdir}/alice-marker.txt`, `alice ${runId}\n`);
	await writeFile(`${bobStatus.workdir}/bob-marker.txt`, `bob ${runId}\n`);
	const aliceBefore = await directoryListing(alice, agentId, aliceSession);
	const bobBefore = await directoryListing(bob, agentId, bobSession);
	assert.ok(aliceBefore.entries.some((entry) => entry.name === 'alice-marker.txt'));
	assert.ok(!aliceBefore.entries.some((entry) => entry.name === 'bob-marker.txt'));
	assert.ok(bobBefore.entries.some((entry) => entry.name === 'bob-marker.txt'));
	assert.ok(!bobBefore.entries.some((entry) => entry.name === 'alice-marker.txt'));
	ok('两个工作区文件互不可见');

	browser = await chromium.launch({ headless: true });
	for (const user of [alice, bob]) {
		const context = await browser.newContext({ locale: 'zh-CN' });
		contexts.push(context);
		await context.addInitScript(() => localStorage.setItem('i18nextLng', 'zh'));
		const page = await context.newPage();
		page.setDefaultTimeout(15000);
		page.on('pageerror', (error) => browserErrors.push(`${user.username}: ${error.message}`));
		page.on('console', (message) => {
			if (message.type() === 'error') {
				browserErrors.push(`${user.username}: ${message.text()}`);
			}
		});
		pages.push(page);
		await login(page, user);
	}
	ok('Alice/Bob 在两个隔离 BrowserContext 中真实登录');

	const [alicePage, bobPage] = pages;
	await toggleResource(alicePage, '/skill/bindings', aliceSkillDisplay);
	assert.equal(await alicePage.getByText(bobSkillDisplay, { exact: true }).count(), 0);
	await toggleResource(bobPage, '/skill/bindings', bobSkillDisplay);
	assert.equal(await bobPage.getByText(aliceSkillDisplay, { exact: true }).count(), 0);
	ok('资源页只显示并更新当前用户自己的 Skill 绑定');

	await toggleResource(alicePage, '/mcp/bindings', aliceMcp);
	assert.equal(await alicePage.getByText(bobMcp, { exact: true }).count(), 0);
	await toggleResource(bobPage, '/mcp/bindings', bobMcp);
	assert.equal(await bobPage.getByText(aliceMcp, { exact: true }).count(), 0);
	ok('资源页只显示并更新当前用户自己的 MCP 绑定');

	const aliceBindings = await api(
		alice,
		`/api/platform/agents/${agentId}/tool-bindings`,
	);
	const bobBindings = await api(bob, `/api/platform/agents/${agentId}/tool-bindings`);
	assert.equal(aliceBindings.skills.find((item) => item.name === aliceSkill)?.enabled, true);
	assert.equal(aliceBindings.mcps.find((item) => item.name === aliceMcp)?.enabled, true);
	assert.equal(bobBindings.skills.find((item) => item.name === bobSkill)?.enabled, true);
	assert.equal(bobBindings.mcps.find((item) => item.name === bobMcp)?.enabled, true);
	assert.ok(!bobBindings.skills.some((item) => item.name === aliceSkill));
	assert.ok(!bobBindings.mcps.some((item) => item.name === aliceMcp));
	ok('真实绑定 API 持久化两组独立的用户 × Agent 白名单');

	const crossBinding = await request(
		bob,
		`/api/platform/agents/${agentId}/tool-bindings`,
		{
			method: 'PUT',
			body: { kind: 'skill', resource_name: aliceSkill, enabled: true },
		},
	);
	assert.equal(crossBinding.status, 404);
	ok('Bob 不能绑定 Alice 的库资源');

	assert.deepEqual(
		(await runtimeSkills(alice, agentId, aliceSession)).map((item) => item.name),
		[aliceSkill],
	);
	assert.deepEqual(
		(await runtimeSkills(bob, agentId, bobSession)).map((item) => item.name),
		[bobSkill],
	);
	assert.deepEqual(
		(await runtimeMcps(alice, agentId, aliceSession)).map((item) => item.name),
		[aliceMcp],
	);
	assert.deepEqual(
		(await runtimeMcps(bob, agentId, bobSession)).map((item) => item.name),
		[bobMcp],
	);
	ok('绑定更新并重新物化后，运行时仅出现各自允许的 Skill/MCP');

	const aliceAfter = await directoryListing(alice, agentId, aliceSession);
	const bobAfter = await directoryListing(bob, agentId, bobSession);
	assert.ok(aliceAfter.entries.some((entry) => entry.name === 'alice-marker.txt'));
	assert.ok(bobAfter.entries.some((entry) => entry.name === 'bob-marker.txt'));
	assert.equal(aliceAfter.path, aliceStatus.workdir);
	assert.equal(bobAfter.path, bobStatus.workdir);
	const aliceSecond = await api(alice, '/sessions/', {
		method: 'POST',
		body: { agent_id: agentId },
	});
	const bobSecond = await api(bob, '/sessions/', {
		method: 'POST',
		body: { agent_id: agentId },
	});
	assert.notEqual(aliceSecond.session_id, aliceSession);
	assert.notEqual(bobSecond.session_id, bobSession);
	assert.equal(
		(await workspaceStatus(alice, agentId, aliceSecond.session_id)).workdir,
		aliceStatus.workdir,
	);
	assert.equal(
		(await workspaceStatus(bob, agentId, bobSecond.session_id)).workdir,
		bobStatus.workdir,
	);
	assert.ok(
		(await directoryListing(alice, agentId, aliceSecond.session_id)).entries.some(
			(entry) => entry.name === 'alice-marker.txt',
		),
	);
	assert.ok(
		(await directoryListing(bob, agentId, bobSecond.session_id)).entries.some(
			(entry) => entry.name === 'bob-marker.txt',
		),
	);
	ok('绑定变更与同用户跨会话均复用原目录并保留文件');

	await bobPage.goto(`${webOrigin}/chat/${agentId}`, { waitUntil: 'domcontentloaded' });
	const agentMenu = bobPage.locator('button:has(svg.lucide-ellipsis)').first();
	await agentMenu.waitFor({ state: 'visible' });
	await agentMenu.click();
	await bobPage.getByRole('menuitem', { name: 'Skill/MCP 绑定', exact: true }).waitFor();
	assert.equal(await bobPage.getByRole('menuitem', { name: '设置', exact: true }).count(), 0);
	assert.equal(
		await bobPage.getByRole('menuitem', { name: '删除智能体', exact: true }).count(),
		0,
	);
	await bobPage.keyboard.press('Escape');
	ok('共享 Agent 聊天页允许绑定但隐藏设置和删除');

	const foreignSession = await request(
		bob,
		withQuery('/workspace/status', { agent_id: agentId, session_id: aliceSession }),
	);
	assert.equal(foreignSession.status, 404);
	const traversal = await request(
		bob,
		withQuery('/workspace/directories', {
			agent_id: agentId,
			session_id: bobSession,
			path: `../${aliceWorkspace}`,
		}),
	);
	assert.equal(traversal.status, 403);
	const absolute = await request(
		bob,
		withQuery('/workspace/directories', {
			agent_id: agentId,
			session_id: bobSession,
			path: aliceStatus.workdir,
		}),
	);
	assert.equal(absolute.status, 403);
	ok('跨用户 session、相对路径穿越和绝对路径访问均被 403/404 拒绝');

	const foreignWorkspaceSession = await api(bob, '/sessions/', {
		method: 'POST',
		body: { agent_id: agentId, workspace_id: aliceWorkspace },
	});
	const foreignWorkspace = await request(
		bob,
		withQuery('/workspace/status', {
			agent_id: agentId,
			session_id: foreignWorkspaceSession.session_id,
		}),
	);
	assert.ok(
		[403, 404].includes(foreignWorkspace.status),
		`跨用户 workspace_id 返回 ${foreignWorkspace.status}: ${foreignWorkspace.text}`,
	);
	ok('显式使用其他用户 workspace_id 被拒绝');

	assert.deepEqual(browserErrors, []);
	ok('两个真实浏览器上下文无 console error / pageerror');

	console.log(
		JSON.stringify(
			{
				result: 'P4-8 live isolation passed',
				checks: passed,
				agentId,
				aliceSession,
				bobSession,
				aliceWorkspace,
				bobWorkspace,
			},
			null,
			2,
		),
	);
} finally {
	for (const context of contexts) await context.close();
	await browser?.close();
}
