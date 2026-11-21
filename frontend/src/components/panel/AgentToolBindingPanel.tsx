import { CircleAlert, Link2, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { AgentToolBinding, AgentToolBindingList, AgentToolKind } from '@/api';
import { agentApi } from '@/api';
import { ResourcePanel } from '@/components/hub/ResourcePanel';
import { AgentSelect } from '@/components/select/AgentSelect';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
	Item,
	ItemActions,
	ItemContent,
	ItemDescription,
	ItemGroup,
	ItemTitle,
} from '@/components/ui/item';
import { Spinner } from '@/components/ui/spinner';
import { Switch } from '@/components/ui/switch';
import { useAgents } from '@/hooks/useAgents';
import { useTranslation } from '@/i18n/useI18n';
import { formatApiErrorForAlert } from '@/lib/api-error';

const EMPTY_BINDINGS: AgentToolBindingList = { skills: [], mcps: [] };

interface AgentToolBindingPanelProps {
	agentId: string;
	/** Resource pages show only their own kind; the Agent dialog shows both. */
	kind?: AgentToolKind;
}

export function AgentToolBindingPanel({ agentId, kind }: AgentToolBindingPanelProps) {
	const { t } = useTranslation();
	const [data, setData] = useState<AgentToolBindingList>(EMPTY_BINDINGS);
	const [loading, setLoading] = useState(true);
	const [pending, setPending] = useState<string | null>(null);
	const [error, setError] = useState('');

	useEffect(() => {
		let current = true;
		setLoading(true);
		setError('');
		setData(EMPTY_BINDINGS);
		agentApi
			.listToolBindings(agentId)
			.then((result) => {
				if (current) setData(result);
			})
			.catch((e) => {
				if (current) setError(formatApiErrorForAlert(e));
			})
			.finally(() => {
				if (current) setLoading(false);
			});
		return () => {
			current = false;
		};
	}, [agentId]);

	const update = async (itemKind: AgentToolKind, item: AgentToolBinding) => {
		const key = `${itemKind}:${item.name}`;
		setPending(key);
		setError('');
		try {
			const updated = await agentApi.updateToolBinding(agentId, {
				kind: itemKind,
				resource_name: item.name,
				enabled: !item.enabled,
			});
			setData((previous) => {
				if (itemKind === 'skill') {
					return {
						...previous,
						skills: previous.skills.map((candidate) =>
							candidate.name === item.name ? updated : candidate,
						),
					};
				}
				return {
					...previous,
					mcps: previous.mcps.map((candidate) =>
						candidate.name === item.name ? updated : candidate,
					),
				};
			});
		} catch (e) {
			setError(formatApiErrorForAlert(e));
		} finally {
			setPending(null);
		}
	};

	const renderSection = (sectionKind: AgentToolKind, items: AgentToolBinding[]) => {
		if (kind && kind !== sectionKind) return null;
		const title = t(`tool-bindings.${sectionKind === 'skill' ? 'skills' : 'mcps'}`);
		return (
			<section className="flex flex-col gap-y-2" key={sectionKind}>
				<h3 className="text-sm font-medium">{title}</h3>
				{items.length === 0 ? (
					<p className="rounded-lg border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
						{t(`tool-bindings.empty.${sectionKind}`)}
					</p>
				) : (
					<ItemGroup className="gap-2">
						{items.map((item) => {
							const displayName = item.display_name || item.name;
							const key = `${sectionKind}:${item.name}`;
							return (
								<Item key={item.name} variant="outline">
									<ItemContent>
										<ItemTitle>
											<span className="truncate">{displayName}</span>
											{!item.installed_enabled && (
												<Badge variant="secondary">
													{t('tool-bindings.installedDisabled')}
												</Badge>
											)}
										</ItemTitle>
										<ItemDescription>{item.name}</ItemDescription>
									</ItemContent>
									<ItemActions>
										{pending === key && <Loader2 className="size-3.5 animate-spin" />}
										<Switch
											aria-label={t('tool-bindings.toggle', { name: displayName })}
											checked={item.enabled}
											disabled={pending !== null || !item.installed_enabled}
											onCheckedChange={() => update(sectionKind, item)}
										/>
									</ItemActions>
								</Item>
							);
						})}
					</ItemGroup>
				)}
			</section>
		);
	};

	return (
		<div className="flex flex-col gap-y-4">
			<p className="text-sm text-muted-foreground">{t('tool-bindings.description')}</p>
			{error && (
				<Alert variant="destructive">
					<CircleAlert />
					<AlertDescription>{error}</AlertDescription>
				</Alert>
			)}
			{loading ? (
				<div className="flex items-center justify-center py-10">
					<Spinner />
				</div>
			) : (
				<>
					{renderSection('skill', data.skills)}
					{renderSection('mcp', data.mcps)}
				</>
			)}
		</div>
	);
}

export function AgentToolBindingResourcePanel({ kind }: { kind: AgentToolKind }) {
	const { t } = useTranslation();
	const { agents, loading } = useAgents();
	const [agentId, setAgentId] = useState<string | null>(null);

	useEffect(() => {
		if (agents.length === 0) {
			setAgentId(null);
			return;
		}
		if (!agents.some((agent) => agent.id === agentId)) setAgentId(agents[0].id);
	}, [agents, agentId]);

	return (
		<ResourcePanel
			title={t('tool-bindings.title')}
			description={t('tool-bindings.resourceDescription')}
			icon={<Link2 className="size-5 text-muted-foreground" />}
		>
			<div className="flex flex-col gap-y-5 p-4">
				<AgentSelect
					agents={agents}
					value={agentId}
					onChange={setAgentId}
					className="w-full"
					placeholder={t('tool-bindings.selectAgent')}
				/>
				{loading ? (
					<div className="flex justify-center py-8">
						<Spinner />
					</div>
				) : agentId ? (
					<AgentToolBindingPanel agentId={agentId} kind={kind} />
				) : (
					<p className="py-8 text-center text-sm text-muted-foreground">
						{t('tool-bindings.noAgents')}
					</p>
				)}
			</div>
		</ResourcePanel>
	);
}
