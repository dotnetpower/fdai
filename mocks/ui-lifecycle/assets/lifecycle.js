// Keyboard paging for the Lifecycle Hub concept screens: Left/Right move through the story, Escape opens the index.
(function () {
  var pages = [
    "01-vendor-release.html",
    "02-vendor-release-activity.html",
    "03-vendor-channels.html",
    "04-vendor-fleet.html",
    "05-hub-installations.html",
    "06-hub-installation-prod.html",
    "07-hub-plan.html",
    "08-console-version.html",
    "09-git-config-pr.html",
    "10-hub-confirmations.html",
    "11-hub-commands.html",
    "12-targethub-bundle-import.html",
    "13-hub-enrollment.html",
    "14-console-policy.html",
  ];
  var index = pages.indexOf(window.location.pathname.split("/").pop());
  if (index < 0) return;
  document.addEventListener("keydown", function (event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    var active = document.activeElement;
    if (active && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)) return;
    if (event.key === "ArrowRight") window.location.href = pages[index + 1] || "index.html";
    if (event.key === "ArrowLeft") window.location.href = index > 0 ? pages[index - 1] : "index.html";
    if (event.key === "Escape") window.location.href = "index.html";
  });
})();
