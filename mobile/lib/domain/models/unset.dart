/// copyWith 的显式清空哨兵，对应 docs/mobile-u1-technical-plan.md 4.2.1。
///
/// 通用规则：不传参数保持原值；显式传 `null` 清空（仅限允许清空的字段）；
/// 显式传非空值更新。参数类型写 `Object?`，实现内用 `identical(value, unset)` 判断，
/// 再 `as T?` 转型。
const Object unset = Object();
