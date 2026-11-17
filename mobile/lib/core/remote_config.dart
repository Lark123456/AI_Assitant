/// 远程模式配置：通过 --dart-define 注入，默认保持 Mock。
///
/// 示例：
/// --dart-define=USE_REMOTE=true
/// --dart-define=BUTLER_API_BASE_URL=http://127.0.0.1:8000
/// --dart-define=BUTLER_USER=<用户 UUID 或飞书 open_id>
class RemoteConfig {
  const RemoteConfig({
    required this.enabled,
    required this.baseUrl,
    required this.user,
  });

  static const fromEnvironment = RemoteConfig(
    enabled: bool.fromEnvironment('USE_REMOTE'),
    baseUrl: String.fromEnvironment(
      'BUTLER_API_BASE_URL',
      defaultValue: 'http://127.0.0.1:8000',
    ),
    user: String.fromEnvironment('BUTLER_USER'),
  );

  final bool enabled;
  final String baseUrl;
  final String user;
}
