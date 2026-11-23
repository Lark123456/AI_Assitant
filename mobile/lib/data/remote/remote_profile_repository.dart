import '../../domain/models/profile.dart';
import '../../domain/repositories/profile_repository.dart';
import 'api_client.dart';

/// U2 我的页真实仓库。
class RemoteProfileRepository implements ProfileRepository {
  RemoteProfileRepository({required this.client});

  final ApiClient client;

  @override
  Future<UserProfile> loadProfile() async {
    final raw = await client.getJson('/api/mobile/profile');
    return UserProfile(
      displayName: _requireString(raw, 'displayName'),
      timezone: _requireString(raw, 'timezone'),
      dayStart: _requireString(raw, 'dayStart'),
      createdAt: _parseDate(raw['createdAt']),
    );
  }
}

String _requireString(Map<String, dynamic> raw, String key) {
  final value = raw[key];
  if (value is! String || value.isEmpty) {
    throw FormatException('缺少字符串字段：$key');
  }
  return value;
}

DateTime _parseDate(Object? raw) {
  if (raw is! String) throw const FormatException('createdAt 必须是字符串');
  return DateTime.parse(raw).toLocal();
}
