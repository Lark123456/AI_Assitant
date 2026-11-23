/// 应用版本常量；不引入 package_info_plus，发布时与 pubspec 手工同步。
const appVersion = String.fromEnvironment(
  'APP_VERSION',
  defaultValue: '0.1.0+1',
);
