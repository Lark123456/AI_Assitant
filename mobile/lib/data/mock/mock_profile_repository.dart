import '../../core/clock.dart';
import '../../domain/models/profile.dart';
import '../../domain/repositories/profile_repository.dart';

/// Mock 我的页资料。
class MockProfileRepository implements ProfileRepository {
  MockProfileRepository({
    required Clock clock,
    this.delay = const Duration(milliseconds: 150),
  }) : _createdAt = clock.now().subtract(const Duration(days: 30));

  final Duration delay;
  final DateTime _createdAt;

  @override
  Future<UserProfile> loadProfile() async {
    await Future<void>.delayed(delay);
    return UserProfile(
      displayName: 'Mock 用户',
      timezone: 'Asia/Shanghai',
      dayStart: '04:00',
      createdAt: _createdAt,
    );
  }
}
