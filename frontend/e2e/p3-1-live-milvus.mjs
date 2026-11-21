import assert from 'node:assert/strict';

const apiOrigin = process.env.AP_API_ORIGIN ?? 'http://127.0.0.1:8000';
const siliconFlowKey = process.env.SILICONFLOW_API_KEY;
assert.ok(siliconFlowKey, 'SILICONFLOW_API_KEY is required');

const runId = Date.now().toString(36);
const username = `p31${runId}`;
const password = `P31!${runId}pass`;
const context = { username, run_id: runId };
let token = '';
let passed = 0;

function ok(label) {
	passed += 1;
	console.log(`PASS ${String(passed).padStart(2, '0')} ${label}`);
}

function withQuery(path, params = {}) {
	const url = new URL(path, apiOrigin);
	for (const [key, value] of Object.entries(params)) {
		url.searchParams.set(key, String(value));
	}
	return `${url.pathname}${url.search}`;
}

async function request(path, { method = 'GET', body, form, authenticated = true } = {}) {
	const headers = {};
	if (authenticated) {
		headers['X-User-ID'] = username;
		if (token) headers.Authorization = `Bearer ${token}`;
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

async function api(path, options = {}, expected = [200, 201, 202, 204]) {
	const response = await request(path, options);
	assert.ok(
		expected.includes(response.status),
		`${options.method ?? 'GET'} ${path} -> ${response.status}: ${response.text}`,
	);
	return response.data;
}

function textOf(value) {
	const content = value?.content;
	if (Array.isArray(content)) {
		return content
			.filter((block) => block.type === 'text')
			.map((block) => block.text)
			.join('\n');
	}
	return content?.type === 'text' ? content.text : '';
}

async function waitForDocument(knowledgeBaseId, documentId) {
	const deadline = Date.now() + 5 * 60 * 1000;
	let lastStatus = 'pending';
	while (Date.now() < deadline) {
		const result = await api(
			withQuery(`/knowledge_bases/${knowledgeBaseId}/documents/status`, {
				ids: documentId,
			}),
		);
		const document = result.items.find((item) => item.id === documentId);
		assert.ok(document, `Document ${documentId} missing from status response`);
		lastStatus = document.status;
		if (document.status === 'ready') return document;
		if (document.status === 'error') {
			throw new Error(`Document ${documentId} indexing failed: ${document.error}`);
		}
		await new Promise((resolve) => setTimeout(resolve, 2000));
	}
	throw new Error(`Document ${documentId} did not become ready; last status=${lastStatus}`);
}

async function search(knowledgeBaseId, query, topK = 3) {
	return api(`/knowledge_bases/${knowledgeBaseId}/search`, {
		method: 'POST',
		body: { query, top_k: topK },
	});
}

const documents = [
	{
		filename: `p31-semantic-harbor-${runId}.txt`,
		text: [
			'星际港口调度手册。曙光七号码头在潮汐风暴期间使用蓝晶信标引导无人飞船。',
			'当能见度下降时，调度员先关闭外侧磁轨，再让飞船沿内侧缓速航道入港。',
			'蓝晶信标每四十七分钟校准一次，校准期间由备用光学浮标接管导航。',
		].join('\n\n'),
	},
	{
		filename: `p31-keyword-repair-${runId}.txt`,
		text: [
			'设备维护工单 ZXQ-7391-OMEGA。该编号用于定位苍穹冷却泵的专用检修记录。',
			'维护人员必须先切断紫色继电器，再使用琥珀扳手松开三层锁止环。',
			'工单 ZXQ-7391-OMEGA 的复核结论是：冷却泵可以安全重启。',
		].join('\n\n'),
	},
	{
		filename: `p31-agent-vault-${runId}.txt`,
		text: [
			'星门验收档案。P3-1 星门验收密码是 NEBULA-7429。',
			'该密码只用于本次知识库检索验收，回答相关问题时应原样给出 NEBULA-7429。',
			'档案另规定：验收员需要先核对密码，再记录星门同步结果。',
		].join('\n\n'),
	},
];

try {
	const auth = await api(
		'/api/platform/auth/register',
		{
			method: 'POST',
			authenticated: false,
			body: { username, password, display_name: username },
		},
	);
	token = auth.access_token;
	assert.ok(token);
	ok('独立 P3-1 用户通过真实 API 注册');

	const credential = await api('/credential/', {
		method: 'POST',
		body: {
			data: {
				type: 'openai_credential',
				name: `SiliconFlow P3-1 ${runId}`,
				api_key: siliconFlowKey,
				base_url: 'https://api.siliconflow.cn/v1',
			},
		},
	});
	context.credential_id = credential.credential_id;
	assert.ok(credential.credential_id);
	ok('硅基流动 OpenAI 兼容凭证已创建');

	const knowledgeBase = await api('/knowledge_bases/', {
		method: 'POST',
		body: {
			name: `P3-1 SiliconFlow Milvus ${runId}`,
			description: '4096 维真实 Milvus、混合检索与 Agent 检索验收',
			embedding_model_config: {
				type: 'openai_credential',
				credential_id: credential.credential_id,
				model: 'Qwen/Qwen3-Embedding-8B',
				dimensions: 4096,
				parameters: {},
			},
		},
	});
	const knowledgeBaseId = knowledgeBase.knowledge_base_id;
	context.knowledge_base_id = knowledgeBaseId;
	assert.ok(knowledgeBaseId);

	const kbList = await api(withQuery('/knowledge_bases/', { id: knowledgeBaseId }));
	const kb = kbList.knowledge_bases.find((item) => item.id === knowledgeBaseId);
	assert.equal(kb?.embedding_model_config.dimensions, 4096);
	assert.equal(kb?.embedding_model_config.model, 'Qwen/Qwen3-Embedding-8B');
	ok('独立 4096 维知识库已创建并读回配置');

	context.documents = [];
	for (const item of documents) {
		const form = new FormData();
		form.append('file', new Blob([item.text], { type: 'text/plain' }), item.filename);
		const uploaded = await api(`/knowledge_bases/${knowledgeBaseId}/documents`, {
			method: 'POST',
			form,
		});
		const ready = await waitForDocument(knowledgeBaseId, uploaded.document_id);
		const chunks = await api(
			withQuery(
				`/knowledge_bases/${knowledgeBaseId}/documents/${uploaded.document_id}/chunks`,
				{ page: 1, page_size: 128 },
			),
		);
		assert.equal(chunks.total, ready.chunk_count);
		assert.ok(chunks.total > 0);
		context.documents.push({
			id: uploaded.document_id,
			filename: item.filename,
			chunk_count: chunks.total,
		});
	}
	assert.equal(context.documents.length, 3);
	ok('三篇文档均达到 ready，文档计数与 Milvus chunk 列表一致');

	const semantic = await search(
		knowledgeBaseId,
		'无人飞船在恶劣天气下怎样安全入港？',
		3,
	);
	assert.ok(semantic.results.length > 0);
	assert.equal(semantic.results[0].document_id, context.documents[0].id);
	context.semantic_top = {
		document_id: semantic.results[0].document_id,
		text: textOf(semantic.results[0].chunk),
	};
	ok('自然语言语义查询命中港口文档');

	const keyword = await search(knowledgeBaseId, 'ZXQ-7391-OMEGA', 3);
	assert.ok(keyword.results.length > 0);
	assert.equal(keyword.results[0].document_id, context.documents[1].id);
	context.keyword_top = {
		document_id: keyword.results[0].document_id,
		text: textOf(keyword.results[0].chunk),
	};
	ok('精确工单编号查询命中维护文档');

	const agent = await api('/agent/', {
		method: 'POST',
		body: {
			name: `P3-1 RAG Agent ${runId}`,
			system_prompt:
				'你是知识库验收助手。只能根据检索到的知识库内容回答；涉及编号或密码时必须原样输出，不得猜测。',
		},
	});
	context.agent_id = agent.agent_id;
	const session = await api('/sessions/', {
		method: 'POST',
		body: {
			agent_id: agent.agent_id,
			chat_model_config: {
				type: 'openai_credential',
				credential_id: credential.credential_id,
				model: 'Qwen/Qwen3-8B',
				model_class: 'openai_chat',
				parameters: { max_tokens: 512, temperature: 0 },
			},
			knowledge_config: {
				knowledge_base_ids: [knowledgeBaseId],
				parameters: {},
			},
		},
	});
	context.session_id = session.session_id;
	ok('带知识库和硅基流动聊天模型的 Agent Session 已创建');

	const trigger = await api('/chat/', {
		method: 'POST',
		body: {
			agent_id: agent.agent_id,
			session_id: session.session_id,
			input: {
				name: 'user',
				role: 'user',
				content: [{ type: 'text', text: '根据知识库，P3-1 星门验收密码是什么？只回答密码。' }],
			},
		},
	});
	assert.ok(['started', 'queued'].includes(trigger.status));

	const deadline = Date.now() + 4 * 60 * 1000;
	let answer = '';
	while (Date.now() < deadline) {
		const messages = await api(
			withQuery(`/sessions/${session.session_id}/messages`, {
				agent_id: agent.agent_id,
				limit: 50,
			}),
		);
		const assistants = messages.messages.filter((message) => message.role === 'assistant');
		const latest = assistants.at(-1);
		if (latest?.error) throw new Error(JSON.stringify(latest.error));
		if (latest?.finished_at && !messages.is_running) {
			answer = textOf(latest);
			break;
		}
		await new Promise((resolve) => setTimeout(resolve, 2000));
	}
	assert.ok(answer, 'Agent did not produce a final answer before timeout');
	assert.ok(answer.includes('NEBULA-7429'), `Agent answer did not use the KB fact: ${answer}`);
	context.agent_answer = answer;
	ok('Agent 真实回答包含仅存在于验收知识库中的密码');

	console.log(`P31_EVIDENCE=${JSON.stringify(context)}`);
} catch (error) {
	console.error(`P31_CONTEXT=${JSON.stringify(context)}`);
	throw error;
}
