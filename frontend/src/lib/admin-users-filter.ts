/**
 * Фильтры экрана «Пользователи».
 *
 * Вынесено из компонента, чтобы правила можно было проверить тестом: именно
 * расхождение между счётчиком и фильтром давало «Сотрудники — 88, список пуст».
 */

export type AdminRole = "employee" | "partner" | "admin" | "superadmin";
export type RoleTab = "all" | "employees" | "partner" | "admins";

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
    case "employees":
      return isEmployeeRole(role);
    case "partner":
      return role === "partner";
    case "admins":
      return isAdminRole(role);
    default:
      return false;
  }
}

export function countByTab(roles: string[], tab: RoleTab): number {
  return roles.filter((role) => matchesRoleTab(role, tab)).length;
}
