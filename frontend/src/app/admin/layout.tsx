import AdminPanelClient from "../adminpanel/adminpanel-client";

import type { ReactNode } from "react";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <AdminPanelClient />
      {children}
    </>
  );
}
