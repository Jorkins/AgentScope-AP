import type { SOPPhase } from '@/api';
import { Badge } from '@/components/ui/badge';
import { useTranslation } from '@/i18n/useI18n';

const PHASE_CLASS: Record<SOPPhase, string> = {
	pending: 'bg-muted text-muted-foreground',
	running: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
	awaiting: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
	completed: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
	failed: 'bg-destructive/15 text-destructive',
};

export function SopPhaseBadge({ phase }: { phase: SOPPhase }) {
	const { t } = useTranslation();
	return (
		<Badge variant="secondary" className={PHASE_CLASS[phase] ?? PHASE_CLASS.pending}>
			{t(`sop.phase.${phase}`)}
		</Badge>
	);
}
