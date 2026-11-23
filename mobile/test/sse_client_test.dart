import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/remote/api_client.dart';

void main() {
  test('getSse 解析事件、多行 data 与注释行', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((request) {
      request.response.headers.contentType = ContentType(
        'text',
        'event-stream',
        charset: 'utf-8',
      );
      request.response.add(
        utf8.encode(
          ': ping\n\n'
          'event: delta\ndata: {"text": "你"}\n\n'
          'event: done\ndata: {"text": "你好",\n'
          'data: "messageId": "r1"}\n\n',
        ),
      );
      request.response.close();
    });
    final client = HttpApiClient(
      baseUrl: 'http://127.0.0.1:${server.port}',
      user: 'dev-user',
    );

    final events = await client.getSse('/stream').toList();

    expect(events.length, 2);
    expect(events[0].event, 'delta');
    expect(events[0].data['text'], '你');
    expect(events[1].event, 'done');
    expect(events[1].data['text'], '你好');
    expect(events[1].data['messageId'], 'r1');
  });

  test('非 2xx 的 SSE 响应抛出 ApiException', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((request) {
      request.response.statusCode = 503;
      request.response.add(utf8.encode('unavailable'));
      request.response.close();
    });
    final client = HttpApiClient(
      baseUrl: 'http://127.0.0.1:${server.port}',
      user: 'dev-user',
    );

    await expectLater(
      client.getSse('/stream').toList(),
      throwsA(isA<ApiException>()),
    );
  });
}
