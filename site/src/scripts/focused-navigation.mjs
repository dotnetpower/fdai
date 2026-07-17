const SIDEBAR_SELECTOR = "#starlight__sidebar";
const TOP_LEVEL_SELECTOR = "ul.top-level";

export function navigationModeForPath(pathname) {
  const path = pathname.replace(/\/+$/, "");
  return /\/(?:ko\/)?sre(?:\/|$)/.test(path) ||
    /\/(?:ko\/)?concepts\/sre-foundations(?:\/|$)/.test(path)
    ? "sre"
    : "global";
}

export function navigationLabels(language) {
  const korean = language.toLowerCase().startsWith("ko");
  return {
    back: korean ? "모든 문서 섹션으로 돌아가기" : "Back to all documentation sections",
  };
}

export function navigationScrollKey(language, mode) {
  const locale = language.toLowerCase().startsWith("ko") ? "ko" : "en";
  return `fdai-sidebar-scroll:${locale}:${mode}`;
}
