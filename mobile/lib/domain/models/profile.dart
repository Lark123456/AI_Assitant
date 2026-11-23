/// 我的页资料：与后端 `/api/mobile/profile` 对齐的只读模型。
class UserProfile {
  const UserProfile({
    required this.displayName,
    required this.timezone,
    required this.dayStart,
    required this.createdAt,
  }) : assert(displayName != '', 'displayName must not be empty'),
       assert(timezone != '', 'timezone must not be empty'),
       assert(dayStart != '', 'dayStart must not be empty');

  final String displayName;
  final String timezone;

  /// "HH:MM"；仅展示，不代表 Today 的切日规则。
  final String dayStart;
  final DateTime createdAt;
}
