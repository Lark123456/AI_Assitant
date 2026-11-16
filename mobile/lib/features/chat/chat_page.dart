import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/enums.dart';
import '../../domain/models/card_action.dart';
import '../../domain/models/chat_message.dart';
import 'chat_controller.dart';

class ChatPage extends ConsumerWidget {
  const ChatPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(chatControllerProvider);
    final networkStatus = ref.watch(networkStatusProvider).value;
    final sendError = async.value?.sendError;

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Friday'),
            Text(S.chatSubtitle, style: Theme.of(context).textTheme.labelSmall),
          ],
        ),
      ),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            if (networkStatus == NetworkStatus.offline)
              const _Banner(text: S.offline, icon: Icons.cloud_off_outlined)
            else if (networkStatus == NetworkStatus.syncing)
              const _Banner(text: S.syncing, icon: Icons.sync),
            if (sendError != null)
              _Banner(text: sendError, icon: Icons.error_outline),
            Expanded(
              child: switch (async) {
                AsyncData(:final value) =>
                  value.messages.isEmpty
                      ? const _EmptyView()
                      : _MessageList(messages: value.messages),
                AsyncError() => _ErrorView(
                  onRetry: () => ref.invalidate(chatControllerProvider),
                ),
                _ => const Center(child: CircularProgressIndicator()),
              },
            ),
            const _Composer(),
          ],
        ),
      ),
    );
  }
}

class _MessageList extends StatefulWidget {
  const _MessageList({required this.messages});

  final List<ChatMessage> messages;

  @override
  State<_MessageList> createState() => _MessageListState();
}

class _MessageListState extends State<_MessageList> {
  final _controller = ScrollController();

  @override
  void didUpdateWidget(covariant _MessageList oldWidget) {
    super.didUpdateWidget(oldWidget);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_controller.hasClients) {
        _controller.jumpTo(_controller.position.maxScrollExtent);
      }
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      controller: _controller,
      padding: const EdgeInsets.all(AppSpacing.lg),
      itemCount: widget.messages.length,
      itemBuilder: (context, index) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: _MessageView(message: widget.messages[index]),
      ),
    );
  }
}

class _MessageView extends ConsumerWidget {
  const _MessageView({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return switch (message) {
      final TextMessage text => _TextBubble(message: text),
      final ConfirmCard card => _ConfirmCardView(card: card),
      final ChoiceCard card => _ChoiceCardView(card: card),
      final MemoryConfirmCard card => _MemoryCardView(card: card),
      final PlanProposalCard card => _PlanCardView(card: card),
      final JarvisIntroCard card => _JarvisIntroView(card: card),
      final ThinkingCard card => _ThinkingView(card: card),
    };
  }
}

class _TextBubble extends ConsumerWidget {
  const _TextBubble({required this.message});

  final TextMessage message;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final isUser = message.sender == ChatSender.user;
    final color = isUser
        ? theme.colorScheme.primary
        : theme.colorScheme.surface;
    final textColor = isUser
        ? theme.colorScheme.onPrimary
        : theme.colorScheme.onSurface;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(AppRadius.card),
          border: isUser ? null : Border.all(color: theme.colorScheme.outline),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${message.text}${message.streaming ? '▍' : ''}',
              style: theme.textTheme.bodyMedium?.copyWith(color: textColor),
            ),
            if (message.syncState == SyncState.queued) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                S.waitingForNetwork,
                style: theme.textTheme.labelSmall?.copyWith(color: textColor),
              ),
            ],
            if (message.syncState == SyncState.failed) ...[
              const SizedBox(height: AppSpacing.xs),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    S.sendFailed,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: textColor,
                    ),
                  ),
                  TextButton(
                    onPressed: () => ref
                        .read(chatControllerProvider.notifier)
                        .retry(message),
                    child: const Text(S.retry),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ConfirmCardView extends ConsumerWidget {
  const _ConfirmCardView({required this.card});

  final ConfirmCard card;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final terminal = card.state != ConfirmCardState.pending;
    return _CardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(card.title, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.xs),
          Text(card.body, style: theme.textTheme.bodySmall),
          if (terminal) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              card.state == ConfirmCardState.confirmed ? S.done : S.skipped,
              style: theme.textTheme.labelSmall,
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              FilledButton(
                onPressed: terminal
                    ? null
                    : () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const ConfirmAction(confirmed: true),
                          ),
                child: Text(card.primaryLabel),
              ),
              const SizedBox(width: AppSpacing.sm),
              OutlinedButton(
                onPressed: terminal
                    ? null
                    : () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const ConfirmAction(confirmed: false),
                          ),
                child: Text(card.secondaryLabel),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ChoiceCardView extends ConsumerWidget {
  const _ChoiceCardView({required this.card});

  final ChoiceCard card;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return _CardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(card.question, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              for (final option in card.options)
                ChoiceChip(
                  label: Text(option),
                  selected: card.answer == option,
                  onSelected: card.answer != null
                      ? null
                      : (_) => ref
                            .read(chatControllerProvider.notifier)
                            .respondToCard(
                              card.id,
                              ChoiceAction(option: option),
                            ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MemoryCardView extends ConsumerWidget {
  const _MemoryCardView({required this.card});

  final MemoryConfirmCard card;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return _CardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final item in card.items)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: Row(
                children: [
                  Expanded(
                    child: Text(item.label, style: theme.textTheme.bodySmall),
                  ),
                  Text(switch (item.state) {
                    MemoryCandidateState.pending => '',
                    MemoryCandidateState.confirmed => S.done,
                    MemoryCandidateState.rejected => S.skipped,
                  }, style: theme.textTheme.labelSmall),
                ],
              ),
            ),
          if (!card.allHandled)
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(
                onPressed: () => ref
                    .read(chatControllerProvider.notifier)
                    .respondToCard(card.id, const ConfirmAllMemoryAction()),
                child: const Text(S.confirmAll),
              ),
            ),
        ],
      ),
    );
  }
}

class _PlanCardView extends ConsumerWidget {
  const _PlanCardView({required this.card});

  final PlanProposalCard card;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final pending = card.state == PlanProposalState.pending;
    return _CardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(card.summary, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.sm),
          for (final change in card.changes)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: Text(
                '· ${change.title}',
                style: theme.textTheme.bodySmall,
              ),
            ),
          Text(card.rationale, style: theme.textTheme.labelSmall),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            children: [
              FilledButton(
                onPressed: pending
                    ? () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const PlanProposalAction(
                              decision: PlanDecision.accept,
                            ),
                          )
                    : null,
                child: const Text(S.planAccept),
              ),
              OutlinedButton(
                onPressed: pending
                    ? () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const PlanProposalAction(
                              decision: PlanDecision.adjust,
                            ),
                          )
                    : null,
                child: const Text(S.planAdjust),
              ),
              TextButton(
                onPressed: pending
                    ? () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const PlanProposalAction(
                              decision: PlanDecision.veto,
                            ),
                          )
                    : null,
                child: const Text(S.planVeto),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _JarvisIntroView extends ConsumerWidget {
  const _JarvisIntroView({required this.card});

  final JarvisIntroCard card;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final open = card.state == JarvisIntroState.open;
    return _CardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(card.summary, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.xs),
          for (final question in card.previewQuestions)
            Text('· $question', style: theme.textTheme.bodySmall),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              FilledButton(
                onPressed: open
                    ? () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const ConfirmAction(confirmed: true),
                          )
                    : null,
                child: const Text(S.jarvisPlan),
              ),
              const SizedBox(width: AppSpacing.sm),
              OutlinedButton(
                onPressed: open
                    ? () => ref
                          .read(chatControllerProvider.notifier)
                          .respondToCard(
                            card.id,
                            const ConfirmAction(confirmed: false),
                          )
                    : null,
                child: const Text(S.jarvisLater),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ThinkingView extends ConsumerWidget {
  const _ThinkingView({required this.card});

  final ThinkingCard card;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return _CardShell(
      child: Row(
        children: [
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text(_phaseText(card.phase), style: theme.textTheme.bodySmall),
        ],
      ),
    );
  }

  String _phaseText(ThinkingPhase phase) => switch (phase) {
    ThinkingPhase.thinking => S.thinking,
    ThinkingPhase.organizing => S.organizing,
    ThinkingPhase.drafting => S.drafting,
    ThinkingPhase.executing => S.executing,
  };
}

class _CardShell extends StatelessWidget {
  const _CardShell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.86,
        ),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: child,
          ),
        ),
      ),
    );
  }
}

class _Composer extends ConsumerStatefulWidget {
  const _Composer();

  @override
  ConsumerState<_Composer> createState() => _ComposerState();
}

class _ComposerState extends ConsumerState<_Composer> {
  final _controller = TextEditingController();
  var _sending = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _sending) return;
    _controller.clear();
    setState(() => _sending = true);
    await ref.read(chatControllerProvider.notifier).sendText(text);
    if (mounted) setState(() => _sending = false);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.sm,
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: InputDecoration(
                hintText: S.inputHint,
                isDense: true,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(AppRadius.button),
                ),
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          FilledButton(
            onPressed: _sending ? null : _send,
            child: const Text(S.send),
          ),
        ],
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.text, required this.icon});

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      color: theme.colorScheme.errorContainer,
      child: Row(
        children: [
          Icon(icon, size: 16, color: theme.colorScheme.onErrorContainer),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: theme.textTheme.labelSmall?.copyWith(
                color: theme.colorScheme.onErrorContainer,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.chat_bubble_outline,
            size: 40,
            color: theme.colorScheme.outline,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(S.chatEmpty, style: theme.textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: 40, color: theme.colorScheme.error),
          const SizedBox(height: AppSpacing.md),
          Text(S.loadingFailed, style: theme.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.md),
          FilledButton(onPressed: onRetry, child: const Text(S.retry)),
        ],
      ),
    );
  }
}
