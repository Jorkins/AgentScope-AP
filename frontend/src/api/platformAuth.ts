/**
 * 平台认证 API（阶段2）。用原生 fetch，避免与 client.ts 形成循环依赖。
 * token 存 localStorage('ap_token')，client.ts 的 buildHeaders 读取并带 Authorization。
 */

export interface AuthResp {
	access_token: string;
	token_type: string;
	username: string;
	tenant_id: string | null;
}

const TOKEN_KEY = 'ap_token';

export const getToken = (): string => localStorage.getItem(TOKEN_KEY) ?? '';
export const setToken = (token: string): void => localStorage.setItem(TOKEN_KEY, token);
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);

async function post(serverUrl: string, path: string, body: unknown): Promise<AuthResp> {
	const url = serverUrl.replace(/\/$/, '') + path;
	let res: Response;
	try {
		res = await fetch(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		});
	} catch {
		throw new Error('无法连接服务器，请检查服务地址');
	}
	if (!res.ok) {
		const text = await res.text();
		let msg = text;
		try {
			const j = JSON.parse(text) as { detail?: unknown };
			msg = typeof j.detail === 'string' ? j.detail : text;
		} catch {
			// 非 JSON，沿用原文
		}
		throw new Error(msg || `请求失败（${res.status}）`);
	}
	return res.json() as Promise<AuthResp>;
}

export const login = (serverUrl: string, username: string, password: string) =>
	post(serverUrl, '/api/platform/auth/login', { username, password });

export const register = (
	serverUrl: string,
	username: string,
	password: string,
	displayName?: string,
) =>
	post(serverUrl, '/api/platform/auth/register', {
		username,
		password,
		display_name: displayName ?? '',
	});
