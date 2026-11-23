import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/core/remote_config.dart';
import 'package:mobile/data/mock/mock_chat_repository.dart';
import 'package:mobile/data/mock/mock_task_repository.dart';
import 'package:mobile/data/mock/mock_today_repository.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_chat_repository.dart';
import 'package:mobile/data/remote/remote_task_repository.dart';
import 'package:mobile/data/remote/remote_today_repository.dart';
import 'package:mobile/domain/enums.dart';

class _FakeApiClient implements ApiClient {
  @override
  Future<Map<String, dynamic>> getJson(String path) async => {};

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) async => {};
}

void main() {
  test('默认装配返回 Mock 仓库', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(chatRepositoryProvider), isA<MockChatRepository>());
    expect(container.read(taskRepositoryProvider), isA<MockTaskRepository>());
    final today = container.read(todayRepositoryProvider);
    expect(today, isA<MockTodayRepository>());
    expect(today.readOnly, isFalse);
  });

  test('远程配置启用时装配可写 Today 仓库', () {
    final container = ProviderContainer(
      overrides: [
        remoteConfigProvider.overrideWithValue(
          const RemoteConfig(
            enabled: true,
            baseUrl: 'http://127.0.0.1:8000',
            user: 'dev-user',
          ),
        ),
        apiClientProvider.overrideWithValue(_FakeApiClient()),
      ],
    );
    addTearDown(container.dispose);

    final today = container.read(todayRepositoryProvider);
    expect(today, isA<RemoteTodayRepository>());
    expect(today.readOnly, isFalse);
    expect(container.read(chatRepositoryProvider), isA<RemoteChatRepository>());
    expect(container.read(taskRepositoryProvider), isA<RemoteTaskRepository>());
  });

  test('网络状态源可切换并广播', () async {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    final source = container.read(mockNetworkStatusSourceProvider);
    expect(await source.watch().first, NetworkStatus.online);

    source.setStatus(NetworkStatus.offline);
    expect(await source.watch().first, NetworkStatus.offline);
  });
}
