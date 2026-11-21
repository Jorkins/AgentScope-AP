import { useState } from 'react';
import { toast } from 'sonner';

import { login, register, setToken } from '@/api/platformAuth';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

interface LoginPageProps {
	onComplete?: () => void;
}

/**
 * 阶段2登录/注册页。登录成功后写入 server_url / ap_token / username，
 * 之后 client.ts 会自动携带 Authorization，后端注入 X-User-ID。
 */
export function LoginPage({ onComplete }: LoginPageProps) {
	const [serverUrl, setServerUrl] = useState(
		() => localStorage.getItem('server_url') ?? 'http://localhost:8000',
	);
	const [username, setUsername] = useState('');
	const [password, setPassword] = useState('');
	const [displayName, setDisplayName] = useState('');
	const [loading, setLoading] = useState(false);

	async function handleSubmit(mode: 'login' | 'register') {
		if (!serverUrl || !username || !password) {
			toast.error('请填写服务地址、用户名和密码');
			return;
		}
		setLoading(true);
		try {
			const resp =
				mode === 'login'
					? await login(serverUrl, username, password)
					: await register(serverUrl, username, password, displayName);
			localStorage.setItem('server_url', serverUrl.replace(/\/$/, ''));
			localStorage.setItem('username', resp.username);
			setToken(resp.access_token);
			toast.success(mode === 'login' ? '登录成功' : '注册成功');
			onComplete?.();
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '操作失败');
		} finally {
			setLoading(false);
		}
	}

	return (
		<div className="flex h-screen items-center justify-center bg-muted/40 p-4">
			<Card className="w-full max-w-md">
				<CardHeader>
					<CardTitle>AgentScope-AP</CardTitle>
					<CardDescription>多 Agent · 多 Skill · 多 MCP · 多租户平台</CardDescription>
				</CardHeader>
				<CardContent className="space-y-4">
					<div className="space-y-2">
						<Label htmlFor="server">服务地址</Label>
						<Input
							id="server"
							value={serverUrl}
							onChange={(e) => setServerUrl(e.target.value)}
							placeholder="http://localhost:8000"
						/>
					</div>
					<Tabs defaultValue="login" className="w-full">
						<TabsList className="grid w-full grid-cols-2">
							<TabsTrigger value="login">登录</TabsTrigger>
							<TabsTrigger value="register">注册</TabsTrigger>
						</TabsList>
						<TabsContent value="login" className="space-y-4 pt-2">
							<div className="space-y-2">
								<Label htmlFor="login-username">用户名</Label>
								<Input
									id="login-username"
									value={username}
									onChange={(e) => setUsername(e.target.value)}
									placeholder="用户名"
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor="login-password">密码</Label>
								<Input
									id="login-password"
									type="password"
									value={password}
									onChange={(e) => setPassword(e.target.value)}
									placeholder="密码"
								/>
							</div>
							<Button
								className="w-full"
								disabled={loading}
								onClick={() => handleSubmit('login')}
							>
								{loading ? '登录中…' : '登录'}
							</Button>
						</TabsContent>
						<TabsContent value="register" className="space-y-4 pt-2">
							<div className="space-y-2">
								<Label htmlFor="reg-display">昵称（可选）</Label>
								<Input
									id="reg-display"
									value={displayName}
									onChange={(e) => setDisplayName(e.target.value)}
									placeholder="昵称"
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor="reg-username">用户名</Label>
								<Input
									id="reg-username"
									value={username}
									onChange={(e) => setUsername(e.target.value)}
									placeholder="至少 2 个字符"
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor="reg-password">密码</Label>
								<Input
									id="reg-password"
									type="password"
									value={password}
									onChange={(e) => setPassword(e.target.value)}
									placeholder="至少 6 位"
								/>
							</div>
							<Button
								className="w-full"
								disabled={loading}
								onClick={() => handleSubmit('register')}
							>
								{loading ? '注册中…' : '注册并登录'}
							</Button>
						</TabsContent>
					</Tabs>
				</CardContent>
			</Card>
		</div>
	);
}

export default LoginPage;
