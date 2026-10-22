"use client";

import { useEffect, useRef } from "react";

/** Shared with the root history guard and sign-out/navigation controls. */
export function useLeaveGuard(active: boolean, message: string, onLeave?: () => void, onCanceled?: () => void) {
  const callbacks = useRef({ onLeave, onCanceled });
  callbacks.current = { onLeave, onCanceled };
  useEffect(() => {
    if (!active) return;
    let leaving = false;
    const currentUrl = window.location.href, currentState = window.history.state;
    const confirm = () => {
      if (!window.confirm(message)) return false;
      leaving = true; callbacks.current.onLeave?.(); return true;
    };
    const beforeUnload = (event: BeforeUnloadEvent) => { if (!leaving) { event.preventDefault(); event.returnValue = ""; } };
    const link = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest<HTMLAnchorElement>("a[href]");
      if (!anchor || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || anchor.target === "_blank" || anchor.hasAttribute("download") || anchor.href === window.location.href) return;
      const next = new URL(anchor.href);
      if (next.pathname === location.pathname && next.search === location.search && next.hash) return;
      if (!confirm()) { event.preventDefault(); event.stopImmediatePropagation(); }
    };
    const navigation = (event: Event) => { if (!confirm()) event.preventDefault(); };
    const history = (event: Event) => { if (location.href !== currentUrl && !confirm()) { event.preventDefault(); window.history.pushState(currentState, "", currentUrl); } };
    const canceled = () => { leaving = false; callbacks.current.onCanceled?.(); };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", link, true);
    window.addEventListener("corelms:before-navigate", navigation);
    window.addEventListener("corelms:before-history", history);
    window.addEventListener("corelms:navigation-canceled", canceled);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload); document.removeEventListener("click", link, true);
      window.removeEventListener("corelms:before-navigate", navigation); window.removeEventListener("corelms:before-history", history);
      window.removeEventListener("corelms:navigation-canceled", canceled);
    };
  }, [active, message]);
}
