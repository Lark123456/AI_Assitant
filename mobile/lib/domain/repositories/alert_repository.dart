import '../models/alert.dart';

/// 紧急提醒来源；处理与关闭都写入决策日志。
abstract interface class AlertRepository {
  Stream<PriorityAlert> watchAlerts();

  Future<void> handleAlert({required String alertId, required String actionId});

  Future<void> dismissAlert(String alertId);
}
