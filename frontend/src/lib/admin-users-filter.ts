/**
 * Фильтры экрана «Пользователи».
 *
 * Вынесено из компонента, чтобы правила можно было проверить тестом: именно
 * расхождение между счётчиком и фильтром давало «Сотрудники — 88, список пуст».
 */

export type AdminRole = "employee" | "partner" | "admin" | "superadmin";
/**
 * «Партнёры» — все обучающиеся: и partner, и legacy employee. Раньше это были
 * две отдельные вкладки, но списки совпадали, поэтому вкладка одна.
 */
export type RoleTab = "all" | "partner" | "admins";

/** Сотрудник — это и обычный employee, и partner: партнёр учится без прав админа. */
export function isEmployeeRole(role: string): boolean {
  return role === "employee" || role === "partner";
}

export function isAdminRole(role: string): boolean {
  return role === "admin" || role === "superadmin";
}

export function matchesRoleTab(role: string, tab: RoleTab): boolean {
  switch (tab) {
    case "all":
      return true;
    case "partner":
      return isEmployeeRole(role);
    case "admins":
      return isAdminRole(role);
    default:
      return false;
  }
}

export function countByTab(roles: string[], tab: RoleTab): number {
  return roles.filter((role) => matchesRoleTab(role, tab)).length;
}
