import '../enums.dart';
import 'conversation.dart';

/// 邀请接受结果：重复或并发接受最多创建一个 Conversation。
sealed class InviteAcceptResult {
  const InviteAcceptResult();
}

final class InviteAccepted extends InviteAcceptResult {
  const InviteAccepted({
    required this.conversation,
    required this.alreadyAccepted,
  });

  final Conversation conversation;
  final bool alreadyAccepted;
}

final class InviteCannotAccept extends InviteAcceptResult {
  const InviteCannotAccept({required this.reason});

  final InviteRejectReason reason;
}

sealed class InviteDeclineResult {
  const InviteDeclineResult();
}

final class InviteDeclined extends InviteDeclineResult {
  const InviteDeclined();
}

final class InviteCannotDecline extends InviteDeclineResult {
  const InviteCannotDecline({required this.reason});

  final InviteRejectReason reason;
}
