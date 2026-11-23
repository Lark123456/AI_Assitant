import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/strings.dart';
import '../../core/theme/tokens.dart';
import '../../domain/enums.dart';
import '../../domain/models/card_action.dart';
import '../../domain/models/chat_message.dart';
import 'chat_controller.dart';

/// Chat 在 4 Tab 外壳中的下标；离开该 Tab 时暂停轮询。
const chatTabIndex = 1;

class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key});

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage>
    with WidgetsBindingObserver {
  var _appActive = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncPolling());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final active = state == AppLifecycleState.resumed;
    if (active == _appActive) return;
    _appActive = active;
    _syncPolling();
  }

  /// 只有“App 在前台且当前 Tab 是 Chat”时才轮询。
  void _syncPolling() {
    if (!mounted) return;
    final selected = ref.read(selectedTabProvider);
    unawaited(
      ref
          .read(chatControllerProvider.notifier)
          .setPollingActive(_appActive && selected == chatTabIndex),
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<int>(selectedTabProvider, (previous, next) => _syncPolling());
    final async = ref.watch(chatControllerProvider);
    final remote = ref.watch(remoteConfigProvider).enabled;
    final networkStatus = remote
        ? null
        : ref.watch(networkStatusProvider).value;
    final sendError = async.value?.sendError;
    final syncError = async.value?.syncError;

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
            if (!remote && networkStatus == NetworkStatus.offline)
              const _Banner(text: S.offline, icon: Icons.cloud_off_outlined)
            else if (!remote && networkStatus == NetworkStatus.syncing)
              const _Banner(text: S.syncing, icon: Icons.sync),
            if (syncError != null)
              _Banner(text: syncError, icon: Icons.sync_problem),
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
  static const _nearBottomThreshold = 120.0;

  final _controller = ScrollController();
  var _atBottom = true;
  var _showNewMessages = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(_onScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToBottom());
  }

  void _onScroll() {
    if (!_controller.hasClients) return;
    final distance = _controller.position.maxScrollExtent - _controller.offset;
    final atBottom = distance <= _nearBottomThreshold;
    _atBottom = atBottom;
    if (atBottom && _showNewMessages) {
      setState(() => _showNewMessages = false);
    }
  }

  void _jumpToBottom() {
    if (!_controller.hasClients) return;
    _controller.jumpTo(_controller.position.maxScrollExtent);
    _atBottom = true;
  }

  @override
  void didUpdateWidget(covariant _MessageList oldWidget) {
    super.didUpdateWidget(oldWidget);
    final grew = widget.messages.length > oldWidget.messages.length;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_atBottom) {
        _jumpToBottom();
      } else if (grew) {
        setState(() => _showNewMessages = true);
      }
    });
  }

  @override
  void dispose() {
    _controller.removeListener(_onScroll);
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        ListView.builder(
          controller: _controller,
          padding: const EdgeInsets.all(AppSpacing.lg),
          itemCount: widget.messages.length,
          itemBuilder: (context, index) => Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.md),
            child: _MessageView(message: widget.messages[index]),
          ),
        ),
        if (_showNewMessages)
          Positioned(
            left: 0,
            right: 0,
            bottom: AppSpacing.md,
            child: Center(
              child: FilledButton.tonalIcon(
                onPressed: () {
                  _controller.animateTo(
                    _controller.position.maxScrollExtent,
                    duration: const Duration(milliseconds: 250),
                    curve: Curves.easeOut,
                  );
                  setState(() => _showNewMessages = false);
                },
                icon: const Icon(Icons.arrow_downward, size: 16),
                label: const Text(S.newMessages),
              ),
            ),
          ),
      ],
    );
  }
}

class _MessageView extends ConsumerWidget {
  const _MessageView({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bubble = switch (message) {
      final TextMessage text => _TextBubble(message: text),
      final ConfirmCard card => _ConfirmCardView(card: card),
      final ChoiceCard card => _ChoiceCardView(card: card),
      final MemoryConfirmCard card => _MemoryCardView(card: card),
      final PlanProposalCard card => _PlanCardView(card: card),
      final JarvisIntroCard card => _JarvisIntroView(card: card),
      final ThinkingCard card => _ThinkingView(card: card),
    };
    if (message.sender == ChatSender.user || message.reason == null) {
      return bubble;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        bubble,
        const SizedBox(height: AppSpacing.xs),
        _ReasonLine(
          reason: message.reason!,
          onTap: () => _showWhySheet(context, message.reason!),
        ),
      ],
    );
  }

  void _showWhySheet(BuildContext context, String reason) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => _WhySheet(reason: reason),
    );
  }
}

class _ReasonLine extends StatelessWidget {
  const _ReasonLine({required this.reason, required this.onTap});

  final String reason;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * 0.86,
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.button),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xs,
            vertical: 2,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.info_outline,
                size: 14,
                color: theme.colorScheme.onSurfaceVariant,
              ),
              const SizedBox(width: AppSpacing.xs),
              Flexible(
                child: Text.rich(
                  TextSpan(
                    text: reason,
                    children: [
                      TextSpan(
                        text: '  ${S.whyPushed}',
                        style: TextStyle(
                          color: theme.colorScheme.primary,
                          decoration: TextDecoration.underline,
                        ),
                      ),
                    ],
                  ),
                  style: theme.textTheme.labelSmall,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WhySheet extends StatelessWidget {
  const _WhySheet({required this.reason});

  final String reason;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final messenger = ScaffoldMessenger.of(context);
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(S.whyPushed, style: theme.textTheme.bodyMedium),
            const SizedBox(height: AppSpacing.sm),
            Text(reason, style: theme.textTheme.bodySmall),
            const SizedBox(height: AppSpacing.md),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.notifications_off_outlined),
              title: const Text(S.quieter),
              onTap: () {
                Navigator.pop(context);
                messenger.showSnackBar(
                  const SnackBar(content: Text(S.quieterNoted)),
                );
              },
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.block),
              title: const Text(S.disableCategory),
              onTap: () {
                Navigator.pop(context);
                messenger.showSnackBar(
                  const SnackBar(content: Text(S.categoryDisabled)),
                );
              },
            ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text(S.gotIt),
              ),
            ),
          ],
        ),
      ),
    );
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
            if (isUser && message.syncState == SyncState.pending) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                S.chatProcessing,
                style: theme.textTheme.labelSmall?.copyWith(color: textColor),
              ),
            ],
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
          TweenAnimationBuilder<double>(
            tween: Tween(begin: 0.4, end: 1),
            duration: const Duration(milliseconds: 600),
            builder: (context, value, child) =>
                Opacity(opacity: value, child: child),
            child: Icon(
              Icons.auto_awesome,
              size: 16,
              color: theme.colorScheme.primary,
            ),
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
  final _focusNode = FocusNode();
  var _sending = false;

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _sending) return;
    _controller.clear();
    await _sendText(text);
  }

  Future<void> _sendQuick(String text) async {
    if (_sending) return;
    await _sendText(text);
  }

  Future<void> _sendText(String text) async {
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
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.xs,
              children: [
                ActionChip(
                  label: const Text(S.quickAddReminder),
                  onPressed: () => _sendQuick(S.quickAddReminder),
                ),
                ActionChip(
                  label: const Text(S.quickPlanToday),
                  onPressed: () => _sendQuick(S.quickPlanToday),
                ),
                ActionChip(
                  label: const Text(S.quickWhatRemember),
                  onPressed: () => _sendQuick(S.quickWhatRemember),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              IconButton(
                tooltip: S.more,
                onPressed: () => _showAttachmentSheet(context),
                icon: const Icon(Icons.add),
              ),
              Expanded(
                child: TextField(
                  controller: _controller,
                  focusNode: _focusNode,
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
        ],
      ),
    );
  }

  void _showAttachmentSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.photo_camera_outlined),
                title: const Text(S.takePhoto),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _showUiOnly(context);
                },
              ),
              ListTile(
                leading: const Icon(Icons.photo_library_outlined),
                title: const Text(S.chooseFromAlbum),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _showUiOnly(context);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showUiOnly(BuildContext context) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text(S.uiOnly)));
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
