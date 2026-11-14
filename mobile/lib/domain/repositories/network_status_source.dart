import '../enums.dart';

/// 整体网络状态来源，与条目级 `SyncState` 不可混用。
abstract interface class NetworkStatusSource {
  Stream<NetworkStatus> watch();
}
