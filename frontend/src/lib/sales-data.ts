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

export const salesTgLinks: SalesLink[] = [
  { title: "Фотографии", url: "https://t.me/+GvD2wEj5AYFiODJi" },
  { title: "Каталоги", url: "https://t.me/+dcE64UQDXQ42OWUy" },
  { title: "Новости", url: "https://t.me/+cwhuXn3x2tY3NmJi" },
  { title: "Договора", url: "https://t.me/+AxOcbXJHVwkxMzAy" },
  { title: "Постройка домов", url: "https://t.me/+_v0wF5ch8o5mNTFi" },
  { title: "Фирменные бани", url: "https://t.me/+z_zsUxFI6SZmZDEy" },
  { title: "Бани Сканди", url: "https://t.me/+Zgmbriz3_t8yMGIy" },
];

export const salesHelpLinks: SalesLink[] = [
  { title: "Почему мы?", url: "https://vkvideo.ru/video-226608360_456239108" },
  { title: "При покупке дома", url: "https://vkvideo.ru/video-226608360_456239354" },
  { title: "При покупке бани", url: "https://vkvideo.ru/video-226608360_456239399?list=61ce5f12c633af10e4" },
];

export const salesContractsLinks: SalesLink[] = [
  { title: "Договора на дома", url: "https://drive.google.com/drive/folders/1bWarZIM06apgsPgvCC17qmhCBsupcy6T?usp=share_link" },
  { title: "Договора на бани", url: "https://drive.google.com/drive/folders/1xaAEEIX0gyZKViX-S_Y65kpdFFTwnNjo?usp=share_link" },
  { title: "Дополнительные договора (1)", url: "https://drive.google.com/drive/folders/1IUuN79nZj0Q3T4GmTMXxyaW4w3RXxD2o?usp=share_link" },
  { title: "Дополнительные договора (2)", url: "https://drive.google.com/drive/folders/1SuyLkQiI55iEM7xHwYJYaZlqLbwelt05?usp=share_link" },
  { title: "Брифы", url: "https://drive.google.com/drive/folders/1N79hGxbdbZ_X_jGgYcpga4NuWJF8Ay9q?usp=share_link" },
  { title: "Регламент по договорам", url: "https://docs.google.com/document/d/18_BEG97kX5tj_opu9GfLfwmys60WO6Ar_j9b_1x6alg/edit?usp=sharing" },
];

export const salesPhotosTree: SalesNode[] = [];

export const salesCatalogsTree: SalesNode[] = [];

export const salesLinksTabs: SalesLinksTab[] = [
  {
    id: "houses",
    label: "Дома",
    tree: [
      { kind: "link", title: "Сенто 107", url: "https://vk.com/video-226608360_456239095" },
      {
        kind: "link",
        title: "Дом с баней 54",
        url: "https://vk.com/kt320?z=video-226608360_456239086%2Fvideos-226608360%2Fpl_-226608360_-2",
      },
      { kind: "link", title: "Сенто 60", url: "https://vk.com/kt320?z=video-226608360_456239084%2Fpl_-226608360_-2" },
      { kind: "link", title: "Сенто 42 Стандарт", url: "https://vk.com/video-226608360_456239051" },
      { kind: "link", title: "Сенто 64", url: "https://vk.com/video-226608360_456239093" },
      { kind: "link", title: "Сенто 24", url: "https://vkvideo.ru/video-226608360_456239020" },
      { kind: "link", title: "Сенто 80", url: "https://vk.com/video-226608360_456239116" },
      { kind: "link", title: "Сенто 42 с террасой ВВ", url: "https://vk.com/video-226608360_456239126" },
      { kind: "link", title: "Сенто 42 СТАНДАРТ", url: "https://vkvideo.ru/video-226608360_456239039" },
      { kind: "link", title: "Барн 69", url: "https://vkvideo.ru/video-226608360_456239203" },
      { kind: "link", title: "Комплекс", url: "https://vkvideo.ru/video-226608360_456239138" },
      { kind: "link", title: "Дом А‑Фрейм", url: "https://rutube.ru/video/b8a37550830794b18acc46e178a1f5f8/" },
      { kind: "link", title: "Идиллия", url: "https://vk.com/clip-226608360_456239189" },
    ],
  },
  {
    id: "baths",
    label: "Бани",
    tree: [
      { kind: "link", title: "Лофт 6 на 2,5 с открытой террасой", url: "https://vk.com/video-226608360_456239052" },
      { kind: "link", title: "Лофт 6 на 2,5", url: "https://vk.com/video-226608360_456239029" },
      { kind: "link", title: "Лофт 6 на 2,5 (PDF)", url: "https://drive.google.com/file/d/189GvbNobjS0RlXqO2y0Yt-frQZi9uAeY/view?usp=share_link" },
      { kind: "link", title: "Лофт угловая", url: "https://drive.google.com/file/d/129NA6e5sN2_zQVwgOb9lU2Xxoku5Y7vM/view?usp=share_link" },
      { kind: "link", title: "Лофт 7 на 2,5", url: "https://drive.google.com/file/d/1AWoJiBEnJfRtlLSZBSIrWxG3VgbJHqfv/view?usp=share_link" },
      { kind: "link", title: "Лофт 7 на 4,5 с террасой", url: "https://vkvideo.ru/video-226608360_456239413" },
      { kind: "link", title: "Барн 47", url: "https://vk.com/video-226608360_456239035" },
      { kind: "link", title: "Тайга", url: "https://vk.com/video-226608360_456239094" },
      { kind: "link", title: "Фирменная с увеличенным предбанником 6 на 4", url: "https://vkvideo.ru/video-226608360_456239034" },
      { kind: "link", title: "Фирменная 6 на 2,5", url: "https://drive.google.com/file/d/1AWoJiBEnJfRtlLSZBSIrWxG3VgbJHqfv/view?usp=share_link" },
      { kind: "link", title: "Фирменная 7 на 4,5 с террасой", url: "https://vk.com/video-226608360_456239024" },
      { kind: "link", title: "Модульная 7 на 5", url: "https://vkvideo.ru/video-226608360_456239133" },
      { kind: "link", title: "Модульная 9 на 6", url: "https://vkvideo.ru/video-226608360_456239171" },
      { kind: "link", title: "Сканди 6 на 2,5 и терраса 6 на 2", url: "https://vkvideo.ru/video-226608360_456239094" },
      { kind: "link", title: "Сканди 6 на 2,5", url: "https://vkvideo.ru/video-226608360_456239042" },
      { kind: "link", title: "Отличия бань: Сканди, Лофт, Фирменная", url: "https://vk.com/video-226608360_456239209" },
    ],
  },
  {
    id: "other",
    label: "Сопутствующие",
    tree: [
      { kind: "link", title: "Этажность 1,5 / 2 / или антресоль", url: "https://vk.com/clip-226608360_456239092" },
      { kind: "link", title: "Черновая отделка", url: "https://vkvideo.ru/video-226608360_456239354" },
      { kind: "link", title: "Предчистовая отделка", url: "https://vk.com/clip-226608360_456239251" },
    ],
  },
  {
    id: "kits",
    label: "Комплектации",
    tree: [
      { kind: "link", title: "Фирменная", url: "https://vk.com/video-226608360_456239032" },
      { kind: "link", title: "Барн", url: "https://vk.com/video-226608360_456239035" },
      { kind: "link", title: "Стандарт", url: "https://vk.com/video-226608360_456239051" },
      { kind: "link", title: "Стандарт +", url: "https://vk.com/video-226608360_456239223" },
      { kind: "link", title: "Все включено", url: "https://vk.com/clip-226608360_456239088" },
    ],
  },
];
