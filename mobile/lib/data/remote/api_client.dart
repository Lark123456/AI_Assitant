import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// 远程 API 的最小客户端；只用 dart:io，不引入网络库。
abstract interface class ApiClient {
  Future<Map<String, dynamic>> getJson(String path);

  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  });
}

/// 一条 SSE 事件；data 为 JSON 对象。
class SseEvent {
  const SseEvent(this.event, this.data);

  final String event;
  final Map<String, dynamic> data;
}

/// SSE 客户端单独成接口，避免给所有 ApiClient Fake 增加方法。
abstract interface class SseClient {
  Stream<SseEvent> getSse(String path);
}

class ApiException implements Exception {
  const ApiException(this.message);

  final String message;

  @override
  String toString() => 'ApiException: $message';
}

class HttpApiClient implements ApiClient, SseClient {
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
      return _decode(response.statusCode, body);
    } finally {
      client.close(force: true);
    }
  }

  @override
  Stream<SseEvent> getSse(String path) async* {
    final client = HttpClient();
    try {
      final request = await client
          .getUrl(Uri.parse('$baseUrl$path'))
          .timeout(timeout);
      request.headers.set('X-Butler-User', user);
      request.headers.set('Accept', 'text/event-stream');
      final response = await request.close().timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = await response
            .transform(utf8.decoder)
            .join()
            .timeout(timeout);
        throw ApiException('HTTP ${response.statusCode}: $body');
      }
      var eventName = 'message';
      final dataLines = <String>[];
      await for (final line
          in response.transform(utf8.decoder).transform(const LineSplitter())) {
        if (line.isEmpty) {
          final event = _decodeSseEvent(eventName, dataLines);
          eventName = 'message';
          dataLines.clear();
          if (event != null) yield event;
          continue;
        }
        if (line.startsWith(':')) continue;
        if (line.startsWith('event:')) {
          eventName = line.substring(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.add(line.substring(5).trimLeft());
        }
      }
      final trailing = _decodeSseEvent(eventName, dataLines);
      if (trailing != null) yield trailing;
    } finally {
      client.close(force: true);
    }
  }

  @override
  Future<Map<String, dynamic>> postJson(
    String path,
    Map<String, dynamic> body, {
    required String idempotencyKey,
  }) async {
    final client = HttpClient();
    try {
      final request = await client
          .postUrl(Uri.parse('$baseUrl$path'))
          .timeout(timeout);
      request.headers.set('X-Butler-User', user);
      request.headers.set('Content-Type', 'application/json; charset=utf-8');
      request.headers.set('Idempotency-Key', idempotencyKey);
      final payload = utf8.encode(jsonEncode(body));
      request.contentLength = payload.length;
      request.add(payload);
      final response = await request.close().timeout(timeout);
      final text = await response
          .transform(utf8.decoder)
          .join()
          .timeout(timeout);
      return _decode(response.statusCode, text);
    } finally {
      client.close(force: true);
    }
  }

  Map<String, dynamic> _decode(int statusCode, String body) {
    if (statusCode < 200 || statusCode >= 300) {
      throw ApiException('HTTP $statusCode: $body');
    }
    if (body.isEmpty) return const {};
    final parsed = jsonDecode(body);
    if (parsed is! Map<String, dynamic>) {
      throw const ApiException('响应不是 JSON 对象');
    }
    return parsed;
  }
}

SseEvent? _decodeSseEvent(String event, List<String> dataLines) {
  if (dataLines.isEmpty) return null;
  final parsed = jsonDecode(dataLines.join('\n'));
  if (parsed is! Map<String, dynamic>) {
    throw const ApiException('SSE 数据不是 JSON 对象');
  }
  return SseEvent(event, parsed);
}
