import { ArrowDown, ArrowLeft, ArrowUp, Plus, Save, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { verifierLabel } from './index';

import type {
	AgentView,
	ChatModelConfig,
	SOPAgentVerifier,
	SOPSessionSettings,
	SOPStepData,
} from '@/api';
import { agentApi, sopApi } from '@/api';
import { AgentSelect } from '@/components/select/AgentSelect';
import { LlmSelect } from '@/components/select/LlmSelect';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';

type VerifierType = 'none' | 'human' | 'agent';

function newStep(index: number): SOPStepData {
	return {
		subject: '',
		description: '',
		executor: { agent_id: '', session_key: `step-${index + 1}` },
		verifier: null,
		max_attempts: 3,
	};
}

interface AgentVerifierFieldsProps {
	verifier: SOPAgentVerifier;
	agents: AgentView[];
	onChange: (verifier: SOPAgentVerifier) => void;
}

function AgentVerifierFields({ verifier, agents, onChange }: AgentVerifierFieldsProps) {
	const { t } = useTranslation();
	return (
		<div className="flex flex-col gap-y-3">
			<div className="grid grid-cols-2 gap-3">
				<AgentSelect
					agents={agents}
					value={verifier.agent.agent_id || null}
					onChange={(agentId) =>
						onChange({ ...verifier, agent: { ...verifier.agent, agent_id: agentId } })
					}
				/>
				<Input
					value={verifier.agent.session_key}
					placeholder={t('sop.editor.sessionKey')}
					onChange={(e) =>
						onChange({ ...verifier, agent: { ...verifier.agent, session_key: e.target.value } })
					}
				/>
			</div>
			<Textarea
				value={verifier.criteria}
				onChange={(e) => onChange({ ...verifier, criteria: e.target.value })}
				placeholder={t('sop.editor.agentCriteria')}
				rows={2}
			/>
		</div>
	);
}

export const SopEditorPage = () => {
	const navigate = useNavigate();
	const { sopId } = useParams<{ sopId?: string }>();
	const { t } = useTranslation();
	const isEdit = Boolean(sopId);

	const [agents, setAgents] = useState<AgentView[]>([]);
	const [name, setName] = useState('');
	const [description, setDescription] = useState('');
	const [steps, setSteps] = useState<SOPStepData[]>([newStep(0)]);
	const [sessionSettings, setSessionSettings] = useState<Record<string, SOPSessionSettings>>({});
	const [saving, setSaving] = useState(false);
	const [loaded, setLoaded] = useState(!isEdit);

	useEffect(() => {
		void agentApi.list().then((resp) => setAgents(resp.agents));
	}, []);

	useEffect(() => {
		if (!sopId) return;
		void sopApi.get(sopId).then((sop) => {
			setName(sop.data.name);
			setDescription(sop.data.description);
			setSteps(sop.data.steps);
			setSessionSettings(sop.data.session_settings ?? {});
			setLoaded(true);
		});
	}, [sopId]);

	// Every session key referenced by an executor or an agent verifier.
	const usedSessionKeys = useMemo(() => {
		const keys = new Set<string>();
		for (const step of steps) {
			if (step.executor.session_key) keys.add(step.executor.session_key);
			if (step.verifier?.type === 'agent' && step.verifier.agent.session_key) {
				keys.add(step.verifier.agent.session_key);
			}
		}
		return [...keys];
	}, [steps]);

	const updateStep = (index: number, patch: Partial<SOPStepData>) => {
		setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
	};

	const moveStep = (index: number, direction: -1 | 1) => {
		setSteps((prev) => {
			const target = index + direction;
			if (target < 0 || target >= prev.length) return prev;
			const next = [...prev];
			[next[index], next[target]] = [next[target], next[index]];
			return next;
		});
	};

	const setVerifierType = (index: number, type: VerifierType) => {
		const step = steps[index];
		if (type === 'none') updateStep(index, { verifier: null });
		else if (type === 'human') {
			updateStep(index, {
				verifier: {
					type: 'human',
					question:
						step.verifier?.type === 'human' ? step.verifier.question : t('sop.verifier.defaultQuestion'),
				},
			});
		} else {
			const existing = step.verifier;
			const agentVerifier = existing?.type === 'agent' ? existing : null;
			updateStep(index, {
				verifier: {
					type: 'agent',
					agent: agentVerifier?.agent ?? {
						agent_id: '',
						session_key: `review-${index + 1}`,
					},
					criteria: agentVerifier?.criteria ?? '',
				},
			});
		}
	};

	const validate = useCallback((): string | null => {
		if (!name.trim()) return t('sop.editor.validation.name');
		if (steps.length === 0) return t('sop.editor.validation.steps');
		const keyAgent = new Map<string, string>();
		const refs: { key: string; agentId: string }[] = [];
		for (const [index, step] of steps.entries()) {
			if (!step.subject.trim() || !step.description.trim()) {
				return t('sop.editor.validation.stepFields', { index: index + 1 });
			}
			if (!step.executor.agent_id || !step.executor.session_key.trim()) {
				return t('sop.editor.validation.executor', { index: index + 1 });
			}
			refs.push({ key: step.executor.session_key, agentId: step.executor.agent_id });
			if (step.verifier?.type === 'agent') {
				if (!step.verifier.agent.agent_id || !step.verifier.agent.session_key.trim()) {
					return t('sop.editor.validation.verifier', { index: index + 1 });
				}
				refs.push({
					key: step.verifier.agent.session_key,
					agentId: step.verifier.agent.agent_id,
				});
			}
		}
		for (const ref of refs) {
			const existing = keyAgent.get(ref.key);
			if (existing && existing !== ref.agentId) return t('sop.editor.validation.sessionShared');
			keyAgent.set(ref.key, ref.agentId);
		}
		for (const key of keyAgent.keys()) {
			if (!sessionSettings[key]?.chat_model_config?.model) {
				return t('sop.editor.validation.model', { key });
			}
		}
		return null;
	}, [name, steps, sessionSettings, t]);

	const handleSave = async () => {
		const error = validate();
		if (error) {
			toast.error(error);
			return;
		}
		const data = {
			name: name.trim(),
			description: description.trim(),
			steps,
			session_settings: Object.fromEntries(
				usedSessionKeys.map((key) => [key, sessionSettings[key]]),
			),
		};
		setSaving(true);
		try {
			if (isEdit && sopId) {
				await sopApi.update(sopId, data);
				toast.success(t('sop.editor.saved'));
				navigate(`/sop/${sopId}`);
			} else {
				const resp = await sopApi.create(data);
				toast.success(t('sop.editor.created'));
				navigate(`/sop/${resp.sop_id}`);
			}
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex size-full flex-col overflow-hidden rounded-[22px] bg-card shadow-panel">
			<div className="shrink-0 flex items-center justify-between gap-x-4 p-[18px_18px_16px]">
				<div className="flex items-center gap-x-3">
					<Button variant="ghost" size="icon-sm" onClick={() => navigate(-1)}>
						<ArrowLeft className="size-4" />
					</Button>
					<span className="text-lg font-medium">
						{isEdit ? t('sop.editor.editTitle') : t('sop.editor.createTitle')}
					</span>
				</div>
				<Button size="sm" disabled={saving || !loaded} onClick={handleSave}>
					<Save className="size-3.5" />
					{t('common.save')}
				</Button>
			</div>
			<Separator className="shrink-0" />

			<div className="min-h-0 flex-1 overflow-y-auto p-[20px_18px_24px]">
				<div className="mx-auto flex max-w-3xl flex-col gap-y-6">
					{/* Basics */}
					<div className="flex flex-col gap-y-3">
						<div className="flex flex-col gap-y-1.5">
							<Label>{t('sop.editor.name')}</Label>
							<Input
								value={name}
								onChange={(e) => setName(e.target.value)}
								placeholder={t('sop.editor.namePlaceholder')}
							/>
						</div>
						<div className="flex flex-col gap-y-1.5">
							<Label>{t('sop.editor.description')}</Label>
							<Textarea
								value={description}
								onChange={(e) => setDescription(e.target.value)}
								placeholder={t('sop.editor.descriptionPlaceholder')}
								rows={2}
							/>
						</div>
					</div>

					{/* Steps */}
					<div className="flex flex-col gap-y-3">
						<div className="flex items-center justify-between">
							<h3 className="text-[13.5px] font-medium">{t('sop.editor.stepsTitle')}</h3>
							<Button
								variant="outline"
								size="sm"
								onClick={() => setSteps((prev) => [...prev, newStep(prev.length)])}
							>
								<Plus className="size-3.5" />
								{t('sop.editor.addStep')}
							</Button>
						</div>
						{steps.map((step, index) => (
							<div key={index} className="border-border flex flex-col gap-y-3 rounded-lg border p-4">
								<div className="flex items-center justify-between">
									<span className="text-sm font-medium">
										{t('sop.editor.stepTitle', { index: index + 1 })}
									</span>
									<div className="flex items-center gap-x-1">
										<Button
											variant="ghost"
											size="icon-xs"
											disabled={index === 0}
											onClick={() => moveStep(index, -1)}
										>
											<ArrowUp className="size-3.5" />
										</Button>
										<Button
											variant="ghost"
											size="icon-xs"
											disabled={index === steps.length - 1}
											onClick={() => moveStep(index, 1)}
										>
											<ArrowDown className="size-3.5" />
										</Button>
										<Button
											variant="ghost"
											size="icon-xs"
											disabled={steps.length <= 1}
											onClick={() => setSteps((prev) => prev.filter((_, i) => i !== index))}
										>
											<Trash2 className="size-3.5" />
										</Button>
									</div>
								</div>
								<div className="grid grid-cols-2 gap-3">
									<div className="flex flex-col gap-y-1.5">
										<Label>{t('sop.editor.stepSubject')}</Label>
										<Input
											value={step.subject}
											onChange={(e) => updateStep(index, { subject: e.target.value })}
										/>
									</div>
									<div className="flex flex-col gap-y-1.5">
										<Label>{t('sop.editor.stepAgent')}</Label>
										<AgentSelect
											agents={agents}
											value={step.executor.agent_id || null}
											onChange={(agentId) =>
												updateStep(index, {
													executor: { ...step.executor, agent_id: agentId },
												})
											}
										/>
									</div>
								</div>
								<div className="flex flex-col gap-y-1.5">
									<Label>{t('sop.editor.stepDescription')}</Label>
									<Textarea
										value={step.description}
										onChange={(e) => updateStep(index, { description: e.target.value })}
										rows={2}
									/>
								</div>
								<div className="grid grid-cols-2 gap-3">
									<div className="flex flex-col gap-y-1.5">
										<Label>{t('sop.editor.sessionKey')}</Label>
										<Input
											value={step.executor.session_key}
											onChange={(e) =>
												updateStep(index, {
													executor: { ...step.executor, session_key: e.target.value },
												})
											}
										/>
									</div>
									<div className="flex flex-col gap-y-1.5">
										<Label>{t('sop.editor.maxAttempts')}</Label>
										<Input
											type="number"
											min={1}
											value={step.max_attempts ?? 3}
											onChange={(e) =>
												updateStep(index, { max_attempts: Math.max(1, Number(e.target.value)) })
											}
										/>
									</div>
								</div>

								{/* Verifier */}
								<div className="flex flex-col gap-y-2">
									<div className="flex items-center gap-x-3">
										<Label>{t('sop.editor.verifierType')}</Label>
										<DropdownMenu>
											<DropdownMenuTrigger asChild>
												<Button variant="outline" size="sm">
													{t(`sop.verifier.${verifierLabel(step.verifier)}`)}
												</Button>
											</DropdownMenuTrigger>
											<DropdownMenuContent align="start">
												{(['none', 'human', 'agent'] as VerifierType[]).map((type) => (
													<DropdownMenuItem key={type} onSelect={() => setVerifierType(index, type)}>
														{t(`sop.verifier.${type}`)}
													</DropdownMenuItem>
												))}
											</DropdownMenuContent>
										</DropdownMenu>
									</div>
									{step.verifier?.type === 'human' && (
										<Textarea
											value={step.verifier.question}
											onChange={(e) =>
												updateStep(index, {
													verifier: { type: 'human', question: e.target.value },
												})
											}
											placeholder={t('sop.editor.humanQuestion')}
											rows={2}
										/>
									)}
									{step.verifier?.type === 'agent' && (
										<AgentVerifierFields
											verifier={step.verifier}
											agents={agents}
											onChange={(verifier) => updateStep(index, { verifier })}
										/>
									)}
								</div>
							</div>
						))}
					</div>

					{/* Session model settings */}
					<div className="flex flex-col gap-y-3">
						<h3 className="text-[13.5px] font-medium">{t('sop.editor.sessionsTitle')}</h3>
						<p className="text-muted-foreground text-xs">{t('sop.editor.sessionsHint')}</p>
						{usedSessionKeys.length === 0 ? (
							<p className="text-muted-foreground text-sm">{t('sop.editor.sessionsEmpty')}</p>
						) : (
							usedSessionKeys.map((key) => (
								<div key={key} className="flex items-center gap-x-3">
									<code className="bg-muted min-w-28 rounded px-2 py-1 text-xs">{key}</code>
									<LlmSelect
										value={sessionSettings[key]?.chat_model_config ?? null}
										onChange={(config: ChatModelConfig | null) =>
											setSessionSettings((prev) => ({
												...prev,
												[key]: { chat_model_config: config! },
											}))
										}
									/>
								</div>
							))
						)}
					</div>
				</div>
			</div>
		</div>
	);
};
