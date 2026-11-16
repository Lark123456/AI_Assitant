import 'dart:async';

import '../../domain/enums.dart';
import '../../domain/repositories/network_status_source.dart';

/// 可手动切换的网络状态源；调试面板与测试共用。
class MockNetworkStatusSource implements NetworkStatusSource {
  MockNetworkStatusSource({NetworkStatus initial = NetworkStatus.online})
    : _current = initial;

  final _controller = StreamController<NetworkStatus>.broadcast(sync: true);
  NetworkStatus _current;

  NetworkStatus get current => _current;

  @override
  Stream<NetworkStatus> watch() {
    late StreamController<NetworkStatus> controller;
    StreamSubscription<NetworkStatus>? subscription;
    controller = StreamController<NetworkStatus>(
      sync: true,
      onListen: () {
        // 先发当前值，再转发后续变化，避免订阅瞬间错过状态切换
        controller.add(_current);
        subscription = _controller.stream.listen(
          controller.add,
          onError: controller.addError,
          onDone: controller.close,
        );
      },
      onCancel: () => subscription?.cancel(),
    );
    return controller.stream;
  }

  void setStatus(NetworkStatus status) {
    if (_current == status) return;
    _current = status;
    _controller.add(status);
  }

  void dispose() {
    _controller.close();
  }
}
