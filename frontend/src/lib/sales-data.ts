export type SalesLink = {
  title: string;
  url: string;
};

export type SalesNode =
  | { kind: "folder"; title: string; children: SalesNode[] }
  | { kind: "link"; title: string; url: string };

export type SalesLinksTabId = "houses" | "baths" | "other" | "kits";

export type SalesLinksTab = {
  id: SalesLinksTabId;
  label: string;
  tree: SalesNode[];
};

export const salesTgLinks: SalesLink[] = [];

export const salesHelpLinks: SalesLink[] = [];

export const salesContractsLinks: SalesLink[] = [];

export const salesPhotosTree: SalesNode[] = [];

export const salesCatalogsTree: SalesNode[] = [];

export const salesLinksTabs: SalesLinksTab[] = [
  { id: "houses", label: "Дома", tree: [] },
  { id: "baths", label: "Бани", tree: [] },
  { id: "other", label: "Сопутствующие", tree: [] },
  { id: "kits", label: "Комплектации", tree: [] },
];
