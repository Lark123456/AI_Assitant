import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/app_info.dart';
import 'package:mobile/core/clock.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/remote_config.dart';
import 'package:mobile/core/strings.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/data/mock/mock_profile_repository.dart';
import 'package:mobile/domain/models/profile.dart';
import 'package:mobile/domain/repositories/profile_repository.dart';
import 'package:mobile/features/profile/profile_page.dart';

final _now = DateTime(2026, 11, 16, 9);

final class _FakeClock implements Clock {
  @override
  DateTime now() => _now;
}

final class _ThrowingRepository implements ProfileRepository {
  @override
  Future<UserProfile> loadProfile() async => throw StateError('boom');
}

Widget _app({ProfileRepository? repository, bool remote = false}) {
  final clock = _FakeClock();
  return ProviderScope(
    overrides: [
      clockProvider.overrideWithValue(clock),
      if (remote)
        remoteConfigProvider.overrideWithValue(
          const RemoteConfig(
            enabled: true,
            baseUrl: 'http://127.0.0.1:8000',
            user: 'dev-user',
          ),
        ),
      profileRepositoryProvider.overrideWithValue(
        repository ?? MockProfileRepository(clock: clock, delay: Duration.zero),
      ),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const ProfilePage()),
  );
}

void main() {
  testWidgets('展示账号、数据源、版本与调试入口', (tester) async {
    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    expect(find.text('Mock 用户'), findsOneWidget);
    expect(find.text('Asia/Shanghai'), findsOneWidget);
    expect(find.text('04:00'), findsOneWidget);
    expect(find.text(S.profileMock), findsOneWidget);
    expect(find.text(appVersion), findsOneWidget);
    expect(find.text(S.profileDebug), findsOneWidget);
  });

  testWidgets('远程模式展示后端地址', (tester) async {
    await tester.pumpWidget(_app(remote: true));
    await tester.pumpAndSettle();

    expect(find.text(S.profileRemote), findsOneWidget);
    expect(find.text('http://127.0.0.1:8000'), findsOneWidget);
  });

  testWidgets('加载失败显示错误与重试', (tester) async {
    await tester.pumpWidget(_app(repository: _ThrowingRepository()));
    await tester.pumpAndSettle();

    expect(find.text(S.loadingFailed), findsOneWidget);
    expect(find.text(S.retry), findsOneWidget);
  });
}
