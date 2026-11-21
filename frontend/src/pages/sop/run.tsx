import { format } from 'date-fns';
import { ArrowLeft, Check, MessagesSquare, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { SopPhaseBadge } from './phase-badge';
import type { AgentView, SOPRunRecord, SOPStepData } from '@/api';
import { agentApi, sopApi } from '@/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from '@/i18n/useI18n';

const ACTIVE_PHASES = new Set(['pending', 'running', 'awaiting']);

interface VerdictCardProps {
	run: SOPRunRecord;
	step: SOPStepData;
	stepIndex: number;
	onSubmitted: () => void;
}

/** Human sign-off for a step parked in `awaiting`. */
function VerdictCard({ run, step, stepIndex, onSubmitted }: VerdictCardProps) {
	const { t } = useTranslation();
	const [message, setMessage] = useState('');
	const [submitting, setSubmitting] = useState(false);
	const question = step.verifier?.type === 'human' ? step.verifier.question : '';

	const submit = async (passed: boolean) => {
		setSubmitting(true);
		try {
			await sopApi.submitVerdict(run.id, {
				step_index: stepIndex,
				passed,
				message: message.trim(),
			});
			setMessage('');
			onSubmitted();
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<div className="border-amber-500/40 bg-amber-500/5 mt-3 flex flex-col gap-y-3 rounded-lg border p-3">
			<p className="text-sm font-medium">{question || t('sop.run.verdict.question')}</p>
			<Textarea
				value={message}
				onChange={(e) => setMessage(e.target.value)}
				placeholder={t('sop.run.verdict.messagePlaceholder')}
				rows={2}
			/>
			<div className="flex items-center gap-x-2">
				<Button size="sm" disabled={submitting} onClick={() => submit(true)}>
					<Check className="size-3.5" />
					{t('sop.run.verdict.approve')}
				</Button>
				<Button
					size="sm"
					variant="outline"
					disabled={submitting}
					onClick={() => submit(false)}
				>
					<X className="size-3.5" />
					{t('sop.run.verdict.reject')}
				</Button>
			</div>
		</div>
	);
}

export const SopRunPage = () => {
	const navigate = useNavigate();
	const { runId } = useParams<{ runId: string }>();
	const { t } = useTranslation();

	const [run, setRun] = useState<SOPRunRecord | null>(null);
	const [agents, setAgents] = useState<AgentView[]>([]);
	const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

	const refresh = useCallback(async () => {
		if (!runId) return;
		const record = await sopApi.getRun(runId, { silent: true });
		setRun(record);
	}, [runId]);

	useEffect(() => {
		void refresh();
		void agentApi.list().then((resp) => setAgents(resp.agents));
	}, [refresh]);

	// Poll while the run is still moving; stop once it settles.
	useEffect(() => {
		if (timerRef.current) {
			clearInterval(timerRef.current);
			timerRef.current = null;
		}
		if (run && ACTIVE_PHASES.has(run.state.phase)) {
			timerRef.current = setInterval(() => void refresh(), 3000);
		}
		return () => {
			if (timerRef.current) clearInterval(timerRef.current);
		};
	}, [run, refresh]);

	const agentName = (agentId: string) =>
		agents.find((a) => a.id === agentId)?.data.name ?? agentId.slice(0, 8);

	return (
		<div className="flex size-full flex-col overflow-hidden rounded-[22px] bg-card shadow-panel">
			<div className="shrink-0 flex items-center justify-between gap-x-4 p-[18px_18px_16px]">
				<div className="flex min-w-0 items-center gap-x-3">
					<Button variant="ghost" size="icon-sm" onClick={() => navigate(-1)}>
						<ArrowLeft className="size-4" />
					</Button>
					<span className="truncate text-lg font-medium">
						{run?.definition.name ?? t('sop.run.title')}
					</span>
					{run && <SopPhaseBadge phase={run.state.phase} />}
				</div>
				{run && (
					<span className="text-muted-foreground shrink-0 font-mono text-xs">
						{run.id.slice(0, 8)} · {format(new Date(run.created_at), 'yyyy-MM-dd HH:mm')}
					</span>
				)}
			</div>
			<Separator className="shrink-0" />

			<div className="min-h-0 flex-1 overflow-y-auto p-[20px_18px_24px]">
				<div className="mx-auto flex max-w-3xl flex-col gap-y-4">
					{run?.definition.steps.map((step, index) => {
						const stepState = run.state.steps[index];
						const phase = stepState?.phase ?? 'pending';
						const sessionId = run.sessions[step.executor.session_key];
						return (
							<div key={index} className="border-border flex flex-col rounded-lg border p-4">
								<div className="flex items-center gap-x-3">
									<span className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full text-xs">
										{index + 1}
									</span>
									<span className="min-w-0 flex-1 truncate text-sm font-medium">
										{step.subject}
									</span>
									<SopPhaseBadge phase={phase} />
								</div>
								<div className="mt-2 flex items-center gap-x-2">
									<Badge variant="outline">{agentName(step.executor.agent_id)}</Badge>
									<Badge variant="secondary">
										{t(`sop.verifier.${step.verifier?.type ?? 'none'}`)}
									</Badge>
									{sessionId && (
										<Button
											variant="ghost"
											size="xs"
											className="text-muted-foreground"
											onClick={() =>
												navigate(`/chat/${step.executor.agent_id}/${sessionId}`)
											}
										>
											<MessagesSquare className="size-3.5" />
											{t('sop.run.viewSession')}
										</Button>
									)}
								</div>

								{/* What the current attempt handed over */}
								{stepState?.submission && stepState.submission.length > 0 && (
									<div className="bg-muted/50 mt-3 rounded-md p-3 text-sm whitespace-pre-wrap">
										{stepState.submission
											.filter((block) => block.type === 'text')
											.map((block) => block.text)
											.join('\n')}
									</div>
								)}

								{/* Settled verdicts, oldest first */}
								{stepState && stepState.verifications.length > 0 && (
									<div className="mt-3 flex flex-col gap-y-1.5">
										{stepState.verifications.map((v, vIndex) => (
											<div key={vIndex} className="flex items-start gap-x-2 text-xs">
												<Badge
													variant="secondary"
													className={
														v.passed
															? 'bg-emerald-500/15 text-emerald-600'
															: 'bg-destructive/15 text-destructive'
													}
												>
													{v.passed ? t('sop.run.verdict.passed') : t('sop.run.verdict.rejected')}
												</Badge>
												<span className="text-muted-foreground flex-1">
													{v.message || '—'}
												</span>
												<span className="text-muted-foreground shrink-0">
													{v.verifier}
												</span>
											</div>
										))}
									</div>
								)}

								{phase === 'awaiting' && step.verifier?.type === 'human' && (
									<VerdictCard run={run} step={step} stepIndex={index} onSubmitted={refresh} />
								)}
							</div>
						);
					})}
				</div>
			</div>
		</div>
	);
};
