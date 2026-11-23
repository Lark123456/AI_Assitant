import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/remote/api_client.dart';
import 'package:mobile/data/remote/remote_profile_repository.dart';

class _FakeApiClient implements ApiClient {
  _FakeApiClient(this.payload);

  final Map<String, dynamic> payload;
  String? lastPath;

  @override
  Future<Map<String, dynamic>> getJson(String path) async {
    lastPath = path;
    return payload;
  }

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) async => const {};
}

void main() {
  test('loadProfile 请求正确路径并解析字段', () async {
    final client = _FakeApiClient({
      'displayName': '张三',
      'timezone': 'Asia/Shanghai',
      'dayStart': '04:00',
      'createdAt': '2026-01-01T08:00:00+08:00',
    });
    final repository = RemoteProfileRepository(client: client);

    final profile = await repository.loadProfile();

    expect(client.lastPath, '/api/mobile/profile');
    expect(profile.displayName, '张三');
    expect(profile.timezone, 'Asia/Shanghai');
    expect(profile.dayStart, '04:00');
    expect(profile.createdAt, DateTime(2026, 1, 1, 8));
  });

  test('缺少字段抛出 FormatException', () async {
    final repository = RemoteProfileRepository(
      client: _FakeApiClient({'displayName': '张三'}),
    );

    expect(repository.loadProfile(), throwsA(isA<FormatException>()));
  });
}
