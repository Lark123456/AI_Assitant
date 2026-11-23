import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/mock/mock_chat_repository.dart';
import '../data/mock/mock_network_status_source.dart';
import '../data/mock/mock_task_repository.dart';
import '../data/mock/mock_today_repository.dart';
import '../data/remote/api_client.dart';
import '../data/remote/remote_chat_repository.dart';
import '../data/remote/remote_task_repository.dart';
import '../data/remote/remote_today_repository.dart';
import '../domain/enums.dart';
import '../domain/repositories/chat_repository.dart';
import '../domain/repositories/task_repository.dart';
import '../domain/repositories/today_repository.dart';
import 'clock.dart';
import 'debug.dart';
import 'remote_config.dart';

/// Provider 装配层：features 只依赖这里暴露的接口，不直接 import data/mock。

/// 当前选中的 Tab；Shell 写入，Chat 页据此暂停/恢复轮询。
class SelectedTab extends Notifier<int> {
  SelectedTab([this.initialIndex = 0]);

  final int initialIndex;

  @override
  int build() => initialIndex;

  void select(int index) => state = index;
}

final selectedTabProvider = NotifierProvider<SelectedTab, int>(SelectedTab.new);

final mockNetworkStatusSourceProvider = Provider<MockNetworkStatusSource>((
  ref,
) {
  final source = MockNetworkStatusSource();
  ref.onDispose(source.dispose);
  return source;
});

final networkStatusProvider = StreamProvider<NetworkStatus>((ref) {
  return ref.watch(mockNetworkStatusSourceProvider).watch();
});

final remoteConfigProvider = Provider<RemoteConfig>((ref) {
  return RemoteConfig.fromEnvironment;
});

final apiClientProvider = Provider<ApiClient>((ref) {
  final config = ref.watch(remoteConfigProvider);
  return HttpApiClient(baseUrl: config.baseUrl, user: config.user);
});

final chatRepositoryProvider = Provider<ChatRepository>((ref) {
  final remote = ref.watch(remoteConfigProvider);
  if (remote.enabled) {
    final repository = RemoteChatRepository(
      client: ref.watch(apiClientProvider),
      clock: ref.watch(clockProvider),
    );
    ref.onDispose(repository.dispose);
    return repository;
  }
  final debug = ref.watch(debugControllerProvider);
  final repository = MockChatRepository(
    clock: ref.watch(clockProvider),
    network: ref.watch(mockNetworkStatusSourceProvider),
    failNextSend: debug.failNextSend,
  );
  ref.onDispose(repository.dispose);
  return repository;
});

final todayRepositoryProvider = Provider<TodayRepository>((ref) {
  final remote = ref.watch(remoteConfigProvider);
  if (remote.enabled) {
    return RemoteTodayRepository(client: ref.watch(apiClientProvider));
  }
  final debug = ref.watch(debugControllerProvider);
  return MockTodayRepository(
    clock: ref.watch(clockProvider),
    dataset: switch (debug.dataset) {
      DebugDataset.normal => MockTodayDataset.normal,
      DebugDataset.empty => MockTodayDataset.empty,
      DebugDataset.error => MockTodayDataset.error,
    },
  );
});

final taskRepositoryProvider = Provider<TaskRepository>((ref) {
  final remote = ref.watch(remoteConfigProvider);
  if (remote.enabled) {
    return RemoteTaskRepository(client: ref.watch(apiClientProvider));
  }
  return MockTaskRepository(clock: ref.watch(clockProvider));
});

/// 调试动作集中在这里，避免 features 直接依赖 data/mock。
class DebugActions {
  DebugActions(this._ref);

  final Ref _ref;

  void injectJarvisIntro() {
    final repository = _ref.read(chatRepositoryProvider);
    if (repository is MockChatRepository) {
      repository.injectJarvisIntro();
    }
  }
}

final debugActionsProvider = Provider<DebugActions>(DebugActions.new);
