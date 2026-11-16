import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/providers.dart';
import 'package:mobile/data/mock/mock_chat_repository.dart';
import 'package:mobile/data/mock/mock_today_repository.dart';
import 'package:mobile/domain/enums.dart';

void main() {
  test('默认装配返回 Mock 仓库', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(chatRepositoryProvider), isA<MockChatRepository>());
    expect(container.read(todayRepositoryProvider), isA<MockTodayRepository>());
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
