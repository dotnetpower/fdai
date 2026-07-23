// Calm Slate - minimal interactions for the UI kit demo.
// The production console is read-only; this script performs no privileged action.
(function () {
  "use strict";

  var navigationGroups = [
    ["Overview", [
      ["dashboard.html", "Dashboard", "is-sage"],
      ["operating-outcomes.html", "Operating outcomes", "is-steel"],
      ["control-assurance.html", "Control assurance", "is-terracotta"],
      ["verticals.html", "Vertical outcomes", "is-plum"],
      ["trust-routing.html", "Trust routing", "is-teal"],
      ["llm-cost.html", "LLM cost", "is-navy"]
    ]],
    ["Console", [
      ["live.html", "Live", ""],
      ["incidents.html", "Incidents", "is-terracotta"],
      ["hil.html", "HIL queue", "is-terracotta"],
      ["promotion.html", "Promotion", "is-teal"],
      ["rules.html", "Rules", ""],
      ["actions.html", "Actions (ontology)", "is-plum"],
      ["audit.html", "Audit", "is-terracotta"],
      ["rca.html", "RCA", "is-teal"]
    ]],
    ["Fleet & safety", [
      ["agents.html", "Fleet roster", "is-sage"],
      ["agents-constellation.html", "Constellation", ""],
      ["pantheon.html", "Pantheon", "is-plum"],
      ["agent-activity.html", "Agent activity", ""],
      ["blast-radius.html", "Blast radius", "is-terracotta"],
      ["provision.html", "Provisioning", ""],
      ["onboarding.html", "Onboarding", "is-dusty-red"]
    ]],
    ["Knowledge", [
      ["ontology.html", "Ontology", "is-plum"],
      ["rule-trace.html", "Rule trace", "is-teal"],
      ["workflow-builder.html", "Workflow builder", ""]
    ]],
    ["Chat", [
      ["deck.html", "Command deck", "is-plum"],
      ["deck-sources.html", "Deck sources", ""]
    ]],
    ["Report & kit", [
      ["report.html", "Weekly report", "is-terracotta"],
      ["rca-report.html", "RCA report", "is-teal"],
      ["settings.html", "Settings", "is-steel"],
      ["components.html", "Components", ""]
    ]],
    ["Explorations", [
      ["agent-icons.html", "Agent icons", "is-plum"],
      ["hcard-variants.html", "HIL card variants", "is-teal"]
    ]]
  ];
  var standalonePageGroups = {
    "settings-diagnostics.html": "Settings",
    "settings-iam.html": "Settings",
    "settings-integrations.html": "Settings",
    "settings-memory.html": "Settings",
    "settings-models.html": "Settings"
  };

  function currentNavigationContext() {
    var currentPage = window.location.pathname.split("/").pop() || "dashboard.html";
    for (var groupIndex = 0; groupIndex < navigationGroups.length; groupIndex += 1) {
      var group = navigationGroups[groupIndex];
      for (var itemIndex = 0; itemIndex < group[1].length; itemIndex += 1) {
        if (group[1][itemIndex][0] === currentPage) {
          return { group: group[0], item: group[1][itemIndex] };
        }
      }
    }
    if (standalonePageGroups[currentPage]) {
      return { group: standalonePageGroups[currentPage], item: [currentPage] };
    }
    return null;
  }

  function decoratePageTitle() {
    var context = currentNavigationContext();
    var heading = document.querySelector("main h1") || document.querySelector("body > header h1");
    if (!context || !heading || heading.querySelector(".cs-page-domain")) return;

    var pageRoot = heading.closest("main") || document.body;
    var titleBlock = heading;
    while (titleBlock.parentElement && titleBlock.parentElement !== pageRoot) {
      titleBlock = titleBlock.parentElement;
    }
    heading.parentElement.prepend(heading);
    pageRoot.prepend(titleBlock);

    var current = document.createElement("span");
    current.className = "cs-page-title-current";
    while (heading.firstChild) current.appendChild(heading.firstChild);

    var domain = document.createElement("span");
    domain.className = "cs-page-domain";
    domain.textContent = context.group;

    var separator = document.createElement("span");
    separator.className = "cs-page-separator";
    separator.setAttribute("aria-hidden", "true");
    separator.textContent = "/";

    heading.classList.add("cs-page-title");
    heading.appendChild(domain);
    heading.appendChild(separator);
    heading.appendChild(current);
  }

  function createNavigation() {
    decoratePageTitle();
    if (window.self !== window.top) {
      document.body.classList.add("cs-embedded");
      return;
    }

    var currentPage = window.location.pathname.split("/").pop() || "dashboard.html";
    var sidebar = document.createElement("aside");
    sidebar.className = "cs-app-sidebar";
    sidebar.setAttribute("aria-label", "Mock navigation");

    var html = '<a class="cs-sidebar-brand" href="dashboard.html"><span class="cs-brand-mark">AW</span> FDAI</a>';
    navigationGroups.forEach(function (group) {
      html += '<section class="cs-sidebar-group"><h2>' + group[0] + '</h2><ul>';
      group[1].forEach(function (item) {
        var active = item[0] === currentPage;
        html += '<li><a href="' + item[0] + '"' + (active ? ' class="cs-active" aria-current="page"' : '') + '>' +
          '<span class="cs-sidebar-dot ' + item[2] + '"></span>' + item[1] + '</a></li>';
      });
      html += "</ul></section>";
    });
    sidebar.innerHTML = html;

    var menuButton = document.createElement("button");
    menuButton.className = "cs-sidebar-menu";
    menuButton.type = "button";
    menuButton.setAttribute("aria-label", "Toggle navigation");
    menuButton.setAttribute("aria-expanded", "false");

    function setNavigationOpen(open) {
      document.body.classList.toggle("cs-sidebar-open", open);
      menuButton.setAttribute("aria-expanded", String(open));
    }

    menuButton.addEventListener("click", function () {
      setNavigationOpen(!document.body.classList.contains("cs-sidebar-open"));
    });

    var backdrop = document.createElement("button");
    backdrop.className = "cs-sidebar-backdrop";
    backdrop.type = "button";
    backdrop.setAttribute("aria-label", "Close navigation");
    backdrop.addEventListener("click", function () { setNavigationOpen(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setNavigationOpen(false);
    });

    document.body.prepend(sidebar);
    document.body.prepend(backdrop);
    document.body.prepend(menuButton);
    document.body.classList.add("cs-has-sidebar");
  }

  document.addEventListener("DOMContentLoaded", createNavigation);

  document.addEventListener("click", function (event) {
    var dismissButton = event.target.closest("[data-cs-dismiss]");
    if (!dismissButton) return;
    var dismissible = dismissButton.closest("[data-cs-dismissible]");
    if (dismissible) dismissible.remove();
  });

  function closeSelectMenus(except) {
    document.querySelectorAll("[data-cs-rich-select]").forEach(function (select) {
      if (select === except) return;
      select.querySelector("[data-cs-select-trigger]").setAttribute("aria-expanded", "false");
      select.querySelector("[data-cs-select-menu]").hidden = true;
    });
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-cs-select-trigger]");
    if (trigger) {
      var select = trigger.closest("[data-cs-rich-select]");
      var menu = select.querySelector("[data-cs-select-menu]");
      var open = menu.hidden;
      closeSelectMenus(select);
      menu.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
      if (open) menu.querySelector('[role="option"][aria-selected="true"]').focus();
      return;
    }
    var option = event.target.closest("[data-cs-rich-select] [role=option]");
    if (option) {
      var owner = option.closest("[data-cs-rich-select]");
      owner.querySelectorAll('[role="option"]').forEach(function (candidate) {
        var selected = candidate === option;
        candidate.setAttribute("aria-selected", String(selected));
        candidate.querySelector(".cs-select-option-check").textContent = selected ? "✓" : "";
      });
      owner.querySelector("[data-cs-select-label]").textContent = option.getAttribute("data-value");
      owner.querySelector("[data-cs-select-secondary]").textContent = option.getAttribute("data-secondary");
      var status = owner.querySelector(".cs-rich-select-button .cs-rich-select-status");
      status.className = "cs-rich-select-status" + (option.getAttribute("data-status") === "watching" ? " is-watching" : option.getAttribute("data-status") === "idle" ? " is-idle" : "");
      owner.querySelector("[data-cs-select-menu]").hidden = true;
      owner.querySelector("[data-cs-select-trigger]").setAttribute("aria-expanded", "false");
      owner.querySelector("[data-cs-select-trigger]").focus();
      return;
    }
    if (!event.target.closest("[data-cs-rich-select]")) closeSelectMenus();
  });

  document.addEventListener("keydown", function (event) {
    var option = event.target.closest("[data-cs-rich-select] [role=option]");
    if (!option || !["ArrowDown", "ArrowUp", "Home", "End", "Enter", " ", "Escape"].includes(event.key)) return;
    var owner = option.closest("[data-cs-rich-select]");
    var options = Array.prototype.slice.call(owner.querySelectorAll('[role="option"]'));
    var index = options.indexOf(option);
    if (event.key === "Escape") {
      owner.querySelector("[data-cs-select-menu]").hidden = true;
      owner.querySelector("[data-cs-select-trigger]").setAttribute("aria-expanded", "false");
      owner.querySelector("[data-cs-select-trigger]").focus();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      option.click();
      return;
    }
    event.preventDefault();
    var next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : index + (event.key === "ArrowDown" ? 1 : -1);
    options[(next + options.length) % options.length].focus();
  });

  function visibleComboboxOptions(combobox) {
    return Array.prototype.slice.call(combobox.querySelectorAll(".cs-combobox-option:not([hidden])"));
  }

  document.addEventListener("input", function (event) {
    var input = event.target.closest("[data-cs-combobox-input]");
    if (!input) return;
    var combobox = input.closest("[data-cs-combobox]");
    var query = input.value.trim().toLowerCase();
    var visible = 0;
    combobox.querySelectorAll(".cs-combobox-option").forEach(function (option) {
      option.hidden = query !== "" && !option.getAttribute("data-search").includes(query);
      option.classList.remove("is-active");
      if (!option.hidden) visible += 1;
    });
    combobox.querySelector("[data-cs-combobox-empty]").hidden = visible !== 0;
    combobox.querySelector("[data-cs-combobox-list]").hidden = false;
    input.setAttribute("aria-expanded", "true");
  });

  document.addEventListener("focusin", function (event) {
    var input = event.target.closest("[data-cs-combobox-input]");
    if (!input) return;
    input.closest("[data-cs-combobox]").querySelector("[data-cs-combobox-list]").hidden = false;
    input.setAttribute("aria-expanded", "true");
  });

  document.addEventListener("keydown", function (event) {
    var input = event.target.closest("[data-cs-combobox-input]");
    if (!input || !["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(event.key)) return;
    var combobox = input.closest("[data-cs-combobox]");
    var options = visibleComboboxOptions(combobox);
    var activeIndex = options.findIndex(function (option) { return option.classList.contains("is-active"); });
    if (event.key === "Escape") {
      combobox.querySelector("[data-cs-combobox-list]").hidden = true;
      input.setAttribute("aria-expanded", "false");
      return;
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      input.value = options[activeIndex].querySelector("strong").textContent;
      combobox.querySelector("[data-cs-combobox-list]").hidden = true;
      input.setAttribute("aria-expanded", "false");
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      var nextIndex = activeIndex + (event.key === "ArrowDown" ? 1 : -1);
      if (activeIndex < 0) nextIndex = event.key === "ArrowDown" ? 0 : options.length - 1;
      options.forEach(function (option) { option.classList.remove("is-active"); });
      if (options.length) options[(nextIndex + options.length) % options.length].classList.add("is-active");
    }
  });

  document.addEventListener("click", function (event) {
    var option = event.target.closest("[data-cs-combobox] .cs-combobox-option");
    if (option) {
      var combobox = option.closest("[data-cs-combobox]");
      var input = combobox.querySelector("[data-cs-combobox-input]");
      input.value = option.querySelector("strong").textContent;
      input.setAttribute("aria-expanded", "false");
      combobox.querySelector("[data-cs-combobox-list]").hidden = true;
      input.focus();
      return;
    }
    if (!event.target.closest("[data-cs-combobox]")) {
      document.querySelectorAll("[data-cs-combobox]").forEach(function (combobox) {
        combobox.querySelector("[data-cs-combobox-list]").hidden = true;
        combobox.querySelector("[data-cs-combobox-input]").setAttribute("aria-expanded", "false");
      });
    }
  });

  function closeDropdownMenu() {
    var trigger = document.querySelector("[data-cs-menu-trigger]");
    var menu = document.querySelector("[data-cs-menu]");
    if (!trigger || !menu) return;
    trigger.setAttribute("aria-expanded", "false");
    menu.hidden = true;
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-cs-menu-trigger]");
    if (trigger) {
      var menu = document.querySelector("[data-cs-menu]");
      var open = menu.hidden;
      menu.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
      if (open) menu.querySelector('[role="menuitem"]').focus();
      return;
    }
    if (event.target.closest("[data-cs-menu] [role=menuitem]")) closeDropdownMenu();
    else if (!event.target.closest("[data-cs-menu]")) closeDropdownMenu();
  });

  document.addEventListener("keydown", function (event) {
    var item = event.target.closest("[data-cs-menu] [role=menuitem]");
    if (!item || !["ArrowDown", "ArrowUp", "Home", "End", "Escape"].includes(event.key)) return;
    var items = Array.prototype.slice.call(item.closest("[data-cs-menu]").querySelectorAll('[role="menuitem"]'));
    var index = items.indexOf(item);
    if (event.key === "Escape") {
      event.preventDefault();
      closeDropdownMenu();
      document.querySelector("[data-cs-menu-trigger]").focus();
      return;
    }
    event.preventDefault();
    var next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : index + (event.key === "ArrowDown" ? 1 : -1);
    items[(next + items.length) % items.length].focus();
  });

  document.addEventListener("input", function (event) {
    var input = event.target.closest("[data-cs-command-input]");
    if (!input) return;
    var command = input.closest("[data-cs-command]");
    var query = input.value.trim().toLowerCase();
    var visible = 0;
    command.querySelectorAll(".cs-command-item").forEach(function (item) {
      item.hidden = query !== "" && !item.getAttribute("data-search").includes(query);
      item.classList.remove("is-active");
      if (!item.hidden) visible += 1;
    });
    var options = Array.prototype.slice.call(command.querySelectorAll(".cs-command-item:not([hidden])"));
    if (options.length) options[0].classList.add("is-active");
    command.querySelector("[data-cs-command-empty]").hidden = visible !== 0;
  });

  document.addEventListener("keydown", function (event) {
    var input = event.target.closest("[data-cs-command-input]");
    if (!input || !["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(event.key)) return;
    var command = input.closest("[data-cs-command]");
    var options = Array.prototype.slice.call(command.querySelectorAll(".cs-command-item:not([hidden])"));
    var activeIndex = options.findIndex(function (item) { return item.classList.contains("is-active"); });
    if (event.key === "Escape") {
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      var label = options[activeIndex].querySelector("strong").textContent;
      command.querySelector("[data-cs-command-result]").textContent = "Selected: " + label;
      return;
    }
    event.preventDefault();
    var next = activeIndex + (event.key === "ArrowDown" ? 1 : -1);
    options.forEach(function (item) { item.classList.remove("is-active"); });
    if (options.length) options[(next + options.length) % options.length].classList.add("is-active");
  });

  var drawerLastTrigger = null;
  function closeDrawer() {
    var overlay = document.querySelector("[data-cs-drawer-overlay]");
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    document.body.classList.remove("cs-drawer-open");
    if (drawerLastTrigger) drawerLastTrigger.focus();
  }

  document.addEventListener("click", function (event) {
    var openButton = event.target.closest("[data-cs-drawer-open]");
    if (openButton) {
      var overlay = document.getElementById(openButton.getAttribute("data-cs-drawer-open"));
      drawerLastTrigger = openButton;
      overlay.hidden = false;
      document.body.classList.add("cs-drawer-open");
      overlay.querySelector("[data-cs-drawer]").focus();
      return;
    }
    if (event.target.closest("[data-cs-drawer-close]")) {
      closeDrawer();
      return;
    }
    if (event.target.matches("[data-cs-drawer-overlay]")) closeDrawer();
  });

  document.addEventListener("keydown", function (event) {
    var drawer = event.target.closest("[data-cs-drawer]");
    if (drawer && event.key === "Tab") {
      var focusables = Array.prototype.slice.call(drawer.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'));
      if (focusables.length) {
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    if (event.key === "Escape") {
      closeDropdownMenu();
      closeDrawer();
    }
  });

  document.addEventListener("click", function (event) {
    var rowButton = event.target.closest("[data-cs-row-select]");
    if (!rowButton) return;
    var table = rowButton.closest("[data-cs-data-table]");
    table.querySelectorAll("[data-cs-row-select]").forEach(function (button) {
      var selected = button === rowButton;
      button.setAttribute("aria-pressed", String(selected));
      button.closest("tr").classList.toggle("is-selected", selected);
    });
  });

  var toastTimer = null;
  function hideToast() {
    var toast = document.querySelector("[data-cs-toast]");
    if (toast) toast.hidden = true;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = null;
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-cs-toast-show]")) {
      var toast = document.querySelector("[data-cs-toast]");
      toast.hidden = false;
      if (toastTimer) window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(hideToast, 5000);
      return;
    }
    if (event.target.closest("[data-cs-toast-close]")) hideToast();
  });

  var calendarMonths = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var calendarEventDays = { "2026-07-06": true, "2026-07-14": true, "2026-07-22": true };

  function calendarDateKey(year, month, day) {
    return year + "-" + String(month + 1).padStart(2, "0") + "-" + String(day).padStart(2, "0");
  }

  function renderCalendar(calendar) {
    var year = Number(calendar.getAttribute("data-year"));
    var month = Number(calendar.getAttribute("data-month"));
    var selectedDate = calendar.getAttribute("data-selected-date");
    var firstWeekday = new Date(year, month, 1).getDay();
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    var weeks = Math.ceil((firstWeekday + daysInMonth) / 7);
    var start = new Date(year, month, 1 - firstWeekday);
    var html = "";
    for (var week = 0; week < weeks; week += 1) {
      html += "<tr>";
      for (var weekday = 0; weekday < 7; weekday += 1) {
        var date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + week * 7 + weekday);
        var key = calendarDateKey(date.getFullYear(), date.getMonth(), date.getDate());
        var outside = date.getMonth() !== month;
        var classes = "cs-calendar-day" + (outside ? " is-outside" : "") + (calendarEventDays[key] ? " has-event" : "");
        html += '<td><button class="' + classes + '" type="button" data-date="' + key + '" aria-pressed="' + String(key === selectedDate) + '">' + date.getDate() + "</button></td>";
      }
      html += "</tr>";
    }
    calendar.querySelector("[data-cs-calendar-title]").textContent = calendarMonths[month] + " " + year;
    calendar.querySelector("[data-cs-calendar-body]").innerHTML = html;
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-cs-calendar]").forEach(renderCalendar);
  });

  document.addEventListener("click", function (event) {
    var navigation = event.target.closest("[data-cs-calendar-nav]");
    if (navigation) {
      var calendar = navigation.closest("[data-cs-calendar]");
      var date = new Date(Number(calendar.getAttribute("data-year")), Number(calendar.getAttribute("data-month")) + Number(navigation.getAttribute("data-cs-calendar-nav")), 1);
      calendar.setAttribute("data-year", String(date.getFullYear()));
      calendar.setAttribute("data-month", String(date.getMonth()));
      calendar.setAttribute("data-selected-date", calendarDateKey(date.getFullYear(), date.getMonth(), 1));
      document.querySelector("[data-cs-schedule-date]").textContent = calendarMonths[date.getMonth()] + " 1, " + date.getFullYear();
      renderCalendar(calendar);
      return;
    }
    var day = event.target.closest(".cs-calendar-day");
    if (!day) return;
    var owner = day.closest("[data-cs-calendar]");
    var selected = day.getAttribute("data-date").split("-").map(Number);
    owner.setAttribute("data-year", String(selected[0]));
    owner.setAttribute("data-month", String(selected[1] - 1));
    owner.setAttribute("data-selected-date", day.getAttribute("data-date"));
    document.querySelector("[data-cs-schedule-date]").textContent = calendarMonths[selected[1] - 1] + " " + selected[2] + ", " + selected[0];
    renderCalendar(owner);
  });

  document.addEventListener("click", function (event) {
    var selection = event.target.closest("[data-cs-segmented] button");
    if (selection) {
      selection.closest("[data-cs-segmented]").querySelectorAll("button").forEach(function (button) {
        var active = button === selection;
        button.classList.toggle("is-active", active);
        button.classList.toggle("cs-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    }

    var pageButton = event.target.closest("[data-cs-pagination] .cs-page-button:not(:disabled)");
    if (pageButton && /^\d+$/.test(pageButton.textContent.trim())) {
      pageButton.closest("[data-cs-pagination]").querySelectorAll(".cs-page-button").forEach(function (button) {
        var active = button === pageButton;
        button.classList.toggle("is-active", active);
        if (active) button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
      });
    }

    var dialogOpen = event.target.closest("[data-cs-dialog-open]");
    if (dialogOpen) {
      var dialog = document.getElementById(dialogOpen.getAttribute("data-cs-dialog-open"));
      if (dialog && typeof dialog.showModal === "function") dialog.showModal();
    }

    var dialogClose = event.target.closest("[data-cs-dialog-close]");
    if (dialogClose) {
      var containingDialog = dialogClose.closest("dialog");
      if (containingDialog) containingDialog.close();
    }
  });

  document.addEventListener("input", function (event) {
    var range = event.target.closest("[data-cs-range]");
    if (!range) return;
    var output = range.parentElement.querySelector("output");
    if (output) output.value = range.value + "%";
  });

  document.addEventListener("click", function (event) {
    var codeTab = event.target.closest("[data-cs-code-tab]");
    if (!codeTab) return;
    var viewer = codeTab.closest("[data-cs-code-viewer]");
    var targetId = codeTab.getAttribute("data-cs-code-tab");
    viewer.querySelectorAll("[data-cs-code-tab]").forEach(function (tab) {
      var active = tab === codeTab;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    viewer.querySelectorAll(".cs-code-panel").forEach(function (panel) {
      panel.hidden = panel.id !== targetId;
    });
    var activePanel = viewer.querySelector("#" + targetId);
    viewer.querySelector("[data-cs-code-file]").textContent = activePanel.getAttribute("data-code-file");
  });

  document.addEventListener("keydown", function (event) {
    var codeTab = event.target.closest("[data-cs-code-tab]");
    if (!codeTab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    var tabs = Array.prototype.slice.call(codeTab.closest("[role=tablist]").querySelectorAll("[data-cs-code-tab]"));
    var currentIndex = tabs.indexOf(codeTab);
    var targetIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : currentIndex + (event.key === "ArrowRight" ? 1 : -1);
    event.preventDefault();
    var targetTab = tabs[(targetIndex + tabs.length) % tabs.length];
    targetTab.focus();
    targetTab.click();
  });

  function copyCodeText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.top = "-1000px";
    document.body.appendChild(textarea);
    textarea.select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch (_) { copied = false; }
    document.body.removeChild(textarea);
    return Promise.resolve(copied);
  }

  document.addEventListener("click", function (event) {
    var copyButton = event.target.closest("[data-cs-code-copy]");
    if (!copyButton) return;
    var viewer = copyButton.closest("[data-cs-code-viewer]");
    var surface = copyButton.closest("[data-cs-code-surface]");
    var activeCode = viewer ? viewer.querySelector(".cs-code-panel:not([hidden]) code") : surface.querySelector("code");
    var lines = activeCode.querySelectorAll(".cs-code-line");
    var text = lines.length ? Array.prototype.map.call(lines, function (line) {
      return line.textContent;
    }).join("\n") : activeCode.textContent;
    copyCodeText(text).then(function (copied) {
      if (!copied) return;
      copyButton.classList.add("is-copied");
      copyButton.textContent = "Copied";
      window.setTimeout(function () {
        copyButton.classList.remove("is-copied");
        copyButton.textContent = "Copy";
      }, 1400);
    });
  });

  document.addEventListener("click", function (event) {
    if (event.target.tagName !== "DIALOG") return;
    var bounds = event.target.getBoundingClientRect();
    var inside = event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
    if (!inside) event.target.close();
  });

  // ---- Tabs (unchanged) -----------------------------------------------------
  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-cs-tab]");
    if (!tab) return;
    var group = tab.closest("[data-cs-tabs]");
    if (!group) return;

    var targetId = tab.getAttribute("data-cs-tab");
    group.querySelectorAll("[data-cs-tab]").forEach(function (t) {
      t.classList.toggle("cs-active", t === tab);
    });

    var container = group.parentElement;
    container.querySelectorAll(".cs-tabpanel").forEach(function (panel) {
      panel.classList.toggle("cs-active", panel.id === targetId);
    });
  });

  // ---- Chart -> data modal --------------------------------------------------
  // Any element with class="js-chartable" becomes clickable. Data attributes:
  //   data-chart-title     : modal title
  //   data-chart-sub       : optional subtitle under the title
  //   data-chart-columns   : JSON array of column labels, e.g. ["Tier","Share"]
  //   data-chart-rows      : JSON array of row arrays
  //   data-chart-num-cols  : optional JSON array of 0-based column indices to
  //                          right-align (tabular numerals)
  //   data-chart-source    : optional footer text (source / window)

  var modalEl = null;
  var lastTrigger = null;

  function ensureModal() {
    if (modalEl) return modalEl;
    modalEl = document.createElement("div");
    modalEl.className = "cs-modal";
    modalEl.setAttribute("role", "dialog");
    modalEl.setAttribute("aria-modal", "true");
    modalEl.setAttribute("aria-labelledby", "cs-modal-title");
    modalEl.hidden = true;
    modalEl.innerHTML = [
      '<div class="cs-modal-panel">',
      '  <div class="cs-modal-head">',
      '    <div>',
      '      <h3 id="cs-modal-title" class="cs-modal-title"></h3>',
      '      <p class="cs-modal-sub" hidden></p>',
      '    </div>',
      '    <button type="button" class="cs-modal-close" aria-label="Close">&times;</button>',
      '  </div>',
      '  <div class="cs-modal-body"></div>',
      '  <div class="cs-modal-foot" hidden></div>',
      '</div>'
    ].join("");
    document.body.appendChild(modalEl);

    modalEl.addEventListener("click", function (e) {
      if (e.target === modalEl) closeModal();
    });
    modalEl.querySelector(".cs-modal-close").addEventListener("click", closeModal);

    return modalEl;
  }

  function parseJSONAttr(el, name) {
    var raw = el.getAttribute(name);
    if (!raw) return null;
    try { return JSON.parse(raw); }
    catch (e) { console.warn("chart modal: bad JSON on", name, raw); return null; }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderTable(columns, rows, numCols) {
    var numSet = {};
    (numCols || []).forEach(function (i) { numSet[i] = true; });

    var thead = "<thead><tr>" + columns.map(function (c, i) {
      var cls = numSet[i] ? ' class="cs-num"' : "";
      return "<th" + cls + ">" + escapeHtml(c) + "</th>";
    }).join("") + "</tr></thead>";

    var tbody = "<tbody>" + rows.map(function (row) {
      return "<tr>" + row.map(function (cell, i) {
        var cls = numSet[i] ? ' class="cs-num"' : "";
        return "<td" + cls + ">" + escapeHtml(cell) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody>";

    return '<div class="cs-table-wrap"><table class="cs-table">' + thead + tbody + "</table></div>";
  }

  function openModal(trigger) {
    var title   = trigger.getAttribute("data-chart-title") || "Details";
    var sub     = trigger.getAttribute("data-chart-sub") || "";
    var source  = trigger.getAttribute("data-chart-source") || "";
    var columns = parseJSONAttr(trigger, "data-chart-columns");
    var rows    = parseJSONAttr(trigger, "data-chart-rows");
    var numCols = parseJSONAttr(trigger, "data-chart-num-cols") || [];

    // Fallback: if the trigger doesn't declare explicit rows, derive them from
    // any descendant carrying data-label + data-value (a common annotation on
    // chart marks). Columns default to ["Point", "Value"].
    if (!rows || !rows.length) {
      var marks = trigger.querySelectorAll("[data-label][data-value]");
      if (marks.length) {
        rows = Array.prototype.map.call(marks, function (m) {
          return [m.getAttribute("data-label"), m.getAttribute("data-value")];
        });
        if (!columns || !columns.length) columns = ["Point", "Value"];
      }
    }
    columns = columns || [];
    rows = rows || [];

    var m = ensureModal();
    m.querySelector(".cs-modal-title").textContent = title;
    var subEl = m.querySelector(".cs-modal-sub");
    if (sub) { subEl.textContent = sub; subEl.hidden = false; }
    else { subEl.hidden = true; }

    m.querySelector(".cs-modal-body").innerHTML = columns.length && rows.length
      ? renderTable(columns, rows, numCols)
      : '<p class="cs-muted">No data provided.</p>';

    var footEl = m.querySelector(".cs-modal-foot");
    if (source) { footEl.textContent = source; footEl.hidden = false; }
    else { footEl.hidden = true; }

    lastTrigger = trigger;
    m.hidden = false;
    document.body.classList.add("cs-modal-open");
    m.querySelector(".cs-modal-close").focus();
  }

  function closeModal() {
    if (!modalEl || modalEl.hidden) return;
    modalEl.hidden = true;
    document.body.classList.remove("cs-modal-open");
    if (lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest(".js-chartable");
    if (!trigger) return;
    if (event.target.closest("a, button, [role=button]") && event.target.closest("a, button, [role=button]") !== trigger) return;
    event.preventDefault();
    openModal(trigger);
  });

  document.addEventListener("keydown", function (event) {
    if (!modalEl || modalEl.hidden) return;
    if (event.key === "Escape") { event.preventDefault(); closeModal(); }
  });

  // Make chartables keyboard-activatable.
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-chartable").forEach(function (el) {
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
      if (!el.hasAttribute("role")) el.setAttribute("role", "button");
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openModal(el); }
      });
    });
  });
})();
