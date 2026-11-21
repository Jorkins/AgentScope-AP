import type { AgentView } from '@/api';
import { AgentToolBindingPanel } from '@/components/panel/AgentToolBindingPanel';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { useTranslation } from '@/i18n/useI18n';

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: AgentView;
}

export function AgentToolBindingsDialog({ open, onOpenChange, agent }: Props) {
	const { t } = useTranslation();

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="!w-[640px] !max-w-[640px]">
				<DialogHeader>
					<DialogTitle>{t('tool-bindings.title')}</DialogTitle>
					<DialogDescription className="sr-only">
						{t('tool-bindings.description')}
					</DialogDescription>
				</DialogHeader>
				<div className="no-scrollbar -mx-4 max-h-[70vh] overflow-y-auto px-4">
					<AgentToolBindingPanel agentId={agent.id} />
				</div>
			</DialogContent>
		</Dialog>
	);
}
