import '../enums.dart';

/// 卡片应答：仅 Confirm / Choice / Memory / PlanProposal 四类。
///
/// 邀请卡片不走 `CardAction`，只调用 `ChatRepository.acceptInvite` /
/// `declineInvite`，避免绕过邀请幂等与 `accepting` 状态。
sealed class CardAction {
  const CardAction();
}

final class ConfirmAction extends CardAction {
  const ConfirmAction({required this.confirmed});

  final bool confirmed;
}

final class ChoiceAction extends CardAction {
  const ChoiceAction({this.option, this.skipped = false})
    : assert(
        skipped || option != null,
        'non-skipped choice action requires an option',
      ),
      assert(
        !skipped || option == null,
        'skipped choice action must not carry an option',
      ),
      assert(option == null || option != '', 'option must not be empty');

  final String? option;
  final bool skipped;
}

final class MemoryAction extends CardAction {
  const MemoryAction({required this.itemId, required this.confirmed})
    : assert(itemId != '', 'itemId must not be empty');

  final String itemId;
  final bool confirmed;
}

final class ConfirmAllMemoryAction extends CardAction {
  const ConfirmAllMemoryAction();
}

final class PlanProposalAction extends CardAction {
  const PlanProposalAction({required this.decision});

  final PlanDecision decision;
}
