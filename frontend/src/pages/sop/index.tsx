import { format } from 'date-fns';
import {
	ArrowRight,
	Ellipsis,
	Pencil,
	Play,
	Plus,
	Trash2,
	Workflow,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { SopPhaseBadge } from './phase-badge';
import type { AgentView, SOPRecord, SOPRunRecord, SOPVerifier } from '@/api';
import { agentApi, sopApi } from '@/api';
import { DeleteDialog } from '@/components/dialog/DeleteDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from '@/components/ui/empty';
import { Separator } from '@/components/ui/separator';
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuAction,
	SidebarMenuButton,
	SidebarMenuItem,
} from '@/components/ui/sidebar';
import { useTranslation } from '@/i18n/useI18n';

export function verifierLabel(verifier: SOPVerifier | null | undefined): string {
	if (!verifier) return 'none';
	return verifier.type;
}

interface DetailPanelProps {
	sop?: SOPRecord;
	agents: AgentView[];
	runs: SOPRunRecord[];
	onStartRun: (sopId: string) => void;
	onDeleteRun: (run: SOPRunRecord) => void;
	starting: boolean;
}

function DetailPanel({ sop, agents, runs, onStartRun, onDeleteRun, starting }: DetailPanelProps) {
	const { t } = useTranslation();
	const navigate = useNavigate();

	if (!sop) {
		return (
			<div className="flex h-full items-center justify-center">
				<Empty className="border-none">
					<EmptyHeader>
						<EmptyMedia variant="icon">
							<Workflow />
						</EmptyMedia>
						<EmptyTitle>{t('sop.selectHint')}</EmptyTitle>
						<EmptyDescription>{t('sop.selectHintDescription')}</EmptyDescription>
					</EmptyHeader>
				</Empty>
			</div>
		);
	}

	const agentName = (agentId: string) =>
		agents.find((a) => a.id === agentId)?.data.name ?? agentId.slice(0, 8);

	return (
		<div className="flex h-full flex-col">
			<div className="shrink-0 flex items-start justify-between gap-x-4 p-[18px_18px_16px]">
				<div className="flex flex-col gap-y-1 min-w-0">
					<span className="truncate text-lg font-medium tracking-[-0.015em] text-foreground">
						{sop.data.name}
					</span>
					{sop.data.description ? (
						<p className="text-sm text-text-data">{sop.data.description}</p>
					) : null}
				</div>
				<div className="flex items-center gap-x-2 shrink-0">
					<Button
						size="sm"
						variant="outline"
						onClick={() => navigate(`/sop/${sop.id}/edit`)}
					>
						<Pencil className="size-3.5" />
						{t('common.edit')}
					</Button>
					<Button size="sm" disabled={starting} onClick={() => onStartRun(sop.id)}>
						<Play className="size-3.5" />
						{t('sop.run.start')}
					</Button>
				</div>
			</div>

			<Separator className="shrink-0" />

			<div className="min-h-0 flex-1 overflow-y-auto p-[20px_18px_24px]">
				<div className="flex flex-col gap-y-6">
					{/* Steps overview */}
					<div className="flex flex-col gap-y-3">
						<h3 className="text-[13.5px] font-medium text-foreground">
							{t('sop.steps.title', { count: sop.data.steps.length })}
						</h3>
						<div className="flex flex-col gap-y-2">
							{sop.data.steps.map((step, index) => (
								<div
									key={index}
									className="border-border bg-card flex items-center gap-x-3 rounded-lg border p-3"
								>
									<span className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full text-xs">
										{index + 1}
									</span>
									<div className="min-w-0 flex-1">
										<div className="truncate text-sm font-medium">{step.subject}</div>
										<div className="text-muted-foreground truncate text-xs">
											{step.description}
										</div>
									</div>
									<Badge variant="outline" className="shrink-0">
										{agentName(step.executor.agent_id)}
									</Badge>
									<Badge variant="secondary" className="shrink-0">
										{t(`sop.verifier.${verifierLabel(step.verifier)}`)}
									</Badge>
								</div>
							))}
						</div>
					</div>

					{/* Run history */}
					<div className="flex flex-col gap-y-3">
						<h3 className="text-[13.5px] font-medium text-foreground">
							{t('sop.runs.title', { count: runs.length })}
						</h3>
						{runs.length === 0 ? (
							<p className="text-muted-foreground text-sm">{t('sop.runs.empty')}</p>
						) : (
							<div className="flex flex-col gap-y-2">
								{runs.map((run) => (
									<div
										key={run.id}
										className="border-border bg-card flex cursor-pointer items-center gap-x-3 rounded-lg border p-3 hover:bg-accent/50"
										onClick={() => navigate(`/sop/runs/${run.id}`)}
									>
										<SopPhaseBadge phase={run.state.phase} />
										<span className="text-muted-foreground font-mono text-xs">
											{run.id.slice(0, 8)}
										</span>
										<span className="text-muted-foreground text-xs">
											{format(new Date(run.created_at), 'yyyy-MM-dd HH:mm')}
										</span>
										<div className="flex-1" />
										<Button
											variant="ghost"
											size="icon-xs"
											title={t('common.delete')}
											onClick={(e) => {
												e.stopPropagation();
												onDeleteRun(run);
											}}
										>
											<Trash2 className="size-3.5" />
										</Button>
										<ArrowRight className="text-muted-foreground size-3.5" />
									</div>
								))}
							</div>
						)}
					</div>
				</div>
			</div>
		</div>
	);
}

export const SopListPage = () => {
	const navigate = useNavigate();
	const { sopId: urlSopId } = useParams<{ sopId?: string }>();
	const { t } = useTranslation();

	const [sops, setSops] = useState<SOPRecord[]>([]);
	const [agents, setAgents] = useState<AgentView[]>([]);
	const [runs, setRuns] = useState<SOPRunRecord[]>([]);
	const [selectedSopId, setSelectedSopId] = useState<string | undefined>(urlSopId);
	const [deleteTarget, setDeleteTarget] = useState<SOPRecord | null>(null);
	const [deleteRunTarget, setDeleteRunTarget] = useState<SOPRunRecord | null>(null);
	const [starting, setStarting] = useState(false);

	const refetchSops = useCallback(async () => {
		const resp = await sopApi.list();
		setSops(resp.sops);
	}, []);

	const refetchRuns = useCallback(async (sopId: string) => {
		const resp = await sopApi.listRuns(sopId);
		setRuns(resp.runs);
	}, []);

	useEffect(() => {
		void refetchSops();
		void agentApi.list().then((resp) => setAgents(resp.agents));
	}, [refetchSops]);

	// Mirror the selection into the URL, defaulting to the first procedure.
	useEffect(() => {
		if (sops.length === 0) return;
		if (sops.some((s) => s.id === selectedSopId)) return;
		const first = sops[0].id;
		setSelectedSopId(first);
		navigate(`/sop/${first}`, { replace: true });
	}, [sops, selectedSopId, navigate]);

	useEffect(() => {
		if (selectedSopId) void refetchRuns(selectedSopId);
		else setRuns([]);
	}, [selectedSopId, refetchRuns]);

	const selectedSop = sops.find((s) => s.id === selectedSopId);

	const handleStartRun = async (sopId: string) => {
		setStarting(true);
		try {
			const run = await sopApi.startRun(sopId);
			navigate(`/sop/runs/${run.id}`);
		} finally {
			setStarting(false);
		}
	};

	const handleConfirmDelete = async () => {
		if (!deleteTarget) return;
		const id = deleteTarget.id;
		await sopApi.delete(id);
		setDeleteTarget(null);
		await refetchSops();
		if (selectedSopId === id) {
			setSelectedSopId(undefined);
			navigate('/sop');
		}
	};

	const handleConfirmDeleteRun = async () => {
		if (!deleteRunTarget) return;
		await sopApi.deleteRun(deleteRunTarget.id);
		setDeleteRunTarget(null);
		if (selectedSopId) await refetchRuns(selectedSopId);
	};

	return (
		<div className="flex size-full p-2 gap-2">
			<Sidebar collapsible="none" className="rounded-[22px]">
				<SidebarHeader className={'flex flex-col p-[20px_18px_14px] gap-y-1'}>
					<div className="text-xl font-medium tracking-[-0.02em] text-foreground">
						{t('common.sop')}
					</div>
					<div className="text-text-tertiary text-xs">{t('sop.subtitle')}</div>
				</SidebarHeader>
				<SidebarContent>
					<SidebarGroup className="mt-6 px-2 py-0">
						<SidebarGroupLabel className="justify-between">
							{t('sop.list.label')}
							<Button
								variant="ghost"
								size="icon-xs"
								onClick={() => navigate('/sop/new')}
								title={t('sop.list.createButton')}
							>
								<Plus className="size-3.5" />
							</Button>
						</SidebarGroupLabel>
						<SidebarGroupContent>
							{sops.length === 0 ? (
								<Empty className="border-none py-4 min-h-50">
									<EmptyHeader>
										<EmptyMedia variant="icon">
											<Workflow />
										</EmptyMedia>
										<EmptyTitle>{t('sop.list.emptyTitle')}</EmptyTitle>
										<EmptyDescription>{t('sop.list.emptyDescription')}</EmptyDescription>
									</EmptyHeader>
									<EmptyContent>
										<Button variant="outline" size="sm" onClick={() => navigate('/sop/new')}>
											<Plus />
											{t('sop.list.createButton')}
										</Button>
									</EmptyContent>
								</Empty>
							) : (
								<SidebarMenu>
									{sops.map((sop) => (
										<SidebarMenuItem key={sop.id}>
											<SidebarMenuButton
												isActive={selectedSopId === sop.id}
												onClick={() => {
													setSelectedSopId(sop.id);
													navigate(`/sop/${sop.id}`);
												}}
											>
												<span className="min-w-0 flex-1 truncate">{sop.data.name}</span>
											</SidebarMenuButton>
											<SidebarMenuAction showOnHover>
												<DropdownMenu>
													<DropdownMenuTrigger asChild>
														<Ellipsis />
													</DropdownMenuTrigger>
													<DropdownMenuContent side="right" align="start">
														<DropdownMenuItem
															onClick={() => navigate(`/sop/${sop.id}/edit`)}
														>
															<Pencil />
															{t('common.edit')}
														</DropdownMenuItem>
														<DropdownMenuItem
															variant="destructive"
															onClick={() => setDeleteTarget(sop)}
														>
															<Trash2 />
															{t('common.delete')}
														</DropdownMenuItem>
													</DropdownMenuContent>
												</DropdownMenu>
											</SidebarMenuAction>
										</SidebarMenuItem>
									))}
								</SidebarMenu>
							)}
						</SidebarGroupContent>
					</SidebarGroup>
				</SidebarContent>
				<SidebarFooter />
			</Sidebar>
			<main className="flex-1 min-h-0 overflow-hidden rounded-[22px] bg-card shadow-panel">
				<DetailPanel
					sop={selectedSop}
					agents={agents}
					runs={runs}
					onStartRun={handleStartRun}
					onDeleteRun={setDeleteRunTarget}
					starting={starting}
				/>
			</main>
			<DeleteDialog
				open={deleteTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDeleteTarget(null);
				}}
				title={t('sop.delete.title')}
				description={t('sop.delete.description', { name: deleteTarget?.data.name ?? '' })}
				onConfirm={handleConfirmDelete}
			/>
			<DeleteDialog
				open={deleteRunTarget !== null}
				onOpenChange={(open) => {
					if (!open) setDeleteRunTarget(null);
				}}
				title={t('sop.runs.delete.title')}
				description={t('sop.runs.delete.description')}
				onConfirm={handleConfirmDeleteRun}
			/>
		</div>
	);
};
