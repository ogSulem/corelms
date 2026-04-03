export type SalesLink = {
  title: string;
  url: string;
};

export type SalesNode =
  | { kind: "folder"; title: string; children: SalesNode[] }
  | { kind: "link"; title: string; url: string };

export const salesTopLinks: SalesLink[] = [
  { title: "Фотографии", url: "https://t.me/+GvD2wEj5AYFiODJi" },
  { title: "Каталоги", url: "https://t.me/+dcE64UQDXQ42OWUy" },
  { title: "Новости", url: "https://t.me/+cwhuXn3x2tY3NmJi" },
  { title: "Договора", url: "https://t.me/+AxOcbXJHVwkxMzAy" },
  { title: "Постройка домов", url: "https://t.me/+_v0wF5ch8o5mNTFi" },
  { title: "Фирменные бани", url: "https://t.me/+z_zsUxFI6SZmZDEy" },
  { title: "Бани Сканди", url: "https://t.me/+Zgmbriz3_t8yMGIy" },
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

export const salesLinksTabs: Array<{ id: "houses" | "baths" | "other"; label: string; tree: SalesNode[] }> = [
  {
    id: "houses",
    label: "Дома",
    tree: [
      {
        kind: "folder",
        title: "Дома",
        children: [
          { kind: "link", title: "Сенто 107", url: "https://vk.com/video-226608360_456239095" },
          { kind: "link", title: "Дом с баней 54", url: "https://vk.com/kt320?z=video-226608360_4562390" },
          { kind: "link", title: "Сенто 60", url: "https://vk.com/kt320?z=video-226608360_4562390" },
          { kind: "link", title: "Сенто 42 Стандарт", url: "https://vk.com/video-226608360_456239051" },
          { kind: "link", title: "Сенто 64", url: "https://vk.com/video-226608360_456239093" },
          { kind: "link", title: "Сенто 24", url: "https://vkvideo.ru/video-226608360_4562390" },
          { kind: "link", title: "Сенто 80", url: "https://vk.com/video-226608360_456239116" },
          { kind: "link", title: "Сенто 42 с террасой ВВ", url: "https://vk.com/video-226608360_456239126" },
          { kind: "link", title: "Сенто 42 СТАНДАРТ", url: "https://vkvideo.ru/video-226608360_4562390" },
          { kind: "link", title: "Барн 69", url: "https://vkvideo.ru/video-226608360_4562392" },
          { kind: "link", title: "Комплекс", url: "https://vkvideo.ru/video-226608360_45623913" },
          { kind: "link", title: "Дом А‑фрейм", url: "https://rutube.ru/video/b8a37550830794b18a" },
          { kind: "link", title: "Идиллия", url: "https://vk.com/clip-226608360_456239189" },
        ],
      },
    ],
  },
  {
    id: "baths",
    label: "Бани",
    tree: [],
  },
  {
    id: "other",
    label: "Сопутствующие",
    tree: [],
  },
];
