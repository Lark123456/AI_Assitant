import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/mock/mock_chat_repository.dart';
import '../data/mock/mock_network_status_source.dart';
import '../data/mock/mock_today_repository.dart';
import '../domain/enums.dart';
import '../domain/repositories/chat_repository.dart';
import '../domain/repositories/today_repository.dart';
import 'clock.dart';

/// Provider 装配层：features 只依赖这里暴露的接口，不直接 import data/mock。

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

final chatRepositoryProvider = Provider<ChatRepository>((ref) {
  final repository = MockChatRepository(
    clock: ref.watch(clockProvider),
    network: ref.watch(mockNetworkStatusSourceProvider),
  );
  ref.onDispose(repository.dispose);
  return repository;
});

final todayRepositoryProvider = Provider<TodayRepository>((ref) {
  return MockTodayRepository(clock: ref.watch(clockProvider));
});
