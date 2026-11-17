import 'dart:convert';
import 'dart:io';

/// 远程 API 的最小客户端；只用 dart:io，不引入网络库。
abstract interface class ApiClient {
  Future<Map<String, dynamic>> getJson(String path);
}

class ApiException implements Exception {
  const ApiException(this.message);

  final String message;

  @override
  String toString() => 'ApiException: $message';
}

class HttpApiClient implements ApiClient {
  HttpApiClient({
    required this.baseUrl,
    required this.user,
    this.timeout = const Duration(seconds: 10),
  });

  final String baseUrl;
  final String user;
  final Duration timeout;

  @override
  Future<Map<String, dynamic>> getJson(String path) async {
    final client = HttpClient();
    try {
      final request = await client
          .getUrl(Uri.parse('$baseUrl$path'))
          .timeout(timeout);
      request.headers.set('X-Butler-User', user);
      final response = await request.close().timeout(timeout);
      final body = await response
          .transform(utf8.decoder)
          .join()
          .timeout(timeout);
      if (response.statusCode != 200) {
        throw ApiException('HTTP ${response.statusCode}: $body');
      }
      final parsed = jsonDecode(body);
      if (parsed is! Map<String, dynamic>) {
        throw const ApiException('响应不是 JSON 对象');
      }
      return parsed;
    } finally {
      client.close(force: true);
    }
  }
}
