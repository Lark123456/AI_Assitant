import '../models/profile.dart';

/// 我的页数据来源：只读资料。
abstract interface class ProfileRepository {
  Future<UserProfile> loadProfile();
}
