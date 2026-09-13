(function () {
  "use strict";

  var navigation = [
    ["knowledge", "Overview", "knowledge.html"],
    ["documents", "Documents", "documents.html"],
    ["github", "GitHub", "github.html"],
    ["gitlab", "GitLab", "gitlab.html"],
    ["azure-devops", "Azure DevOps", "azure-devops.html"]
  ];

  var sources = {
    github: {
      title: "GitHub",
      identity: "App installation",
      scope: "Organization and repository allowlist",
      integration: "Server-owned GitHub App",
      records: [
        {
          id: "gh-runbooks",
          name: "platform/runbooks",
          ref: "main",
          authorization: "Authorized",
          freshness: "Fresh",
          tone: "success",
          coverage: "42 indexed refs",
          observed: "2026-08-27T10:11:00Z",
          receipt: "obs-gh-104"
        },
        {
          id: "gh-catalog",
          name: "services/catalog",
          ref: "release/v3",
          authorization: "Authorized",
          freshness: "Stale",
          tone: "warning",
          coverage: "118 indexed refs",
          observed: "2026-08-27T09:28:00Z",
          receipt: "obs-gh-103"
        },
        {
          id: "gh-reviews",
          name: "operations/reviews",
          ref: "main",
          authorization: "Unavailable",
          freshness: "Unknown",
          tone: "neutral",
          coverage: "Not available",
          observed: "No successful observation",
          receipt: "None"
        }
      ]
    },
    gitlab: {
      title: "GitLab",
      identity: "Project token broker",
      scope: "Group and project allowlist",
      integration: "Server-owned token broker",
      records: [
        {
          id: "gl-playbooks",
          name: "delivery/playbooks",
          ref: "main",
          authorization: "Authorized",
          freshness: "Fresh",
          tone: "success",
          coverage: "36 indexed refs",
          observed: "2026-08-27T10:08:00Z",
          receipt: "obs-gl-091"
        },
        {
          id: "gl-policies",
          name: "governance/policies",
          ref: "reviewed",
          authorization: "Authorized",
          freshness: "Stale",
          tone: "warning",
          coverage: "64 indexed refs",
          observed: "2026-08-27T09:21:00Z",
          receipt: "obs-gl-088"
        },
        {
          id: "gl-handovers",
          name: "sre/handovers",
          ref: "main",
          authorization: "Unavailable",
          freshness: "Unknown",
          tone: "neutral",
          coverage: "Not available",
          observed: "No successful observation",
          receipt: "None"
        }
      ]
    },
    "azure-devops": {
      title: "Azure DevOps",
      identity: "Workload identity",
      scope: "Organization, project, and repository allowlist",
      integration: "Server-owned service connection",
      records: [
        {
          id: "ado-runbooks",
          name: "Platform / Runbooks",
          ref: "main",
          authorization: "Authorized",
          freshness: "Fresh",
          tone: "success",
          coverage: "51 indexed refs",
          observed: "2026-08-27T10:06:00Z",
          receipt: "obs-ado-072"
        },
        {
          id: "ado-catalog",
          name: "Services / Catalog",
          ref: "release",
          authorization: "Authorized",
          freshness: "Stale",
          tone: "warning",
          coverage: "93 indexed refs",
          observed: "2026-08-27T09:16:00Z",
          receipt: "obs-ado-069"
        },
        {
          id: "ado-reviews",
          name: "Operations / Reviews",
          ref: "main",
          authorization: "Unavailable",
          freshness: "Unknown",
          tone: "neutral",
          coverage: "Not available",
          observed: "No successful observation",
          receipt: "None"
        }
      ]
    }
  };

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function status(text, tone) {
    return '<span class="kw-status is-' + escapeHtml(tone || "neutral") + '">' +
      escapeHtml(text) + "</span>";
  }

  function sourceNavigation(pageId) {
    return '<nav class="kw-source-nav" aria-label="Knowledge sources">' +
      navigation.map(function (item) {
        return '<a href="' + item[2] + '"' + (item[0] === pageId ? ' aria-current="page"' : "") +
          ">" + escapeHtml(item[1]) + "</a>";
      }).join("") + "</nav>";
  }

  function pageHeader(page, pageId, common) {
    return '<header class="kw-header"><div class="kw-header-copy"><h1><span class="kw-domain">Knowledge</span>' +
      '<span class="kw-separator" aria-hidden="true">/</span><span>' +
      escapeHtml(page.variant === "overview" ? "Overview" : page.title) +
      "</span></h1><p>" + escapeHtml(page.subtitle) +
      '</p></div><dl class="kw-header-meta"><div><dt>Evidence mode</dt><dd>Synthetic specimen</dd></div>' +
      '<div><dt>Recorded at</dt><dd><time datetime="' + escapeHtml(common.asOf) + '">' +
      escapeHtml(common.asOf) + "</time></dd></div></dl></header>" + sourceNavigation(pageId);
  }

  function boundary(message) {
    return '<div class="kw-boundary" role="note"><strong>Read-only specimen.</strong><span>' +
      escapeHtml(message) + "</span></div>";
  }

  function renderOverview(page, pageId, common) {
    var sourceRows = [
      {
        href: "documents.html",
        title: "Documents",
        kind: "Managed upload",
        state: "Preview available",
        tone: "info",
        summary: "Review consent, collection policy, protection checks, indexing, and durable processing receipts.",
        boundary: "Collection ACL"
      },
      {
        href: "github.html",
        title: "GitHub",
        kind: "Repository connector",
        state: "Setup required",
        tone: "warning",
        summary: "Review the server-owned GitHub App boundary before any repository can be observed.",
        boundary: "App installation"
      },
      {
        href: "gitlab.html",
        title: "GitLab",
        kind: "Repository connector",
        state: "Setup required",
        tone: "warning",
        summary: "Review the project token broker and allowlisted synchronization scope.",
        boundary: "Token broker"
      },
      {
        href: "azure-devops.html",
        title: "Azure DevOps",
        kind: "Repository connector",
        state: "Setup required",
        tone: "warning",
        summary: "Review workload identity, project scope, and the server-owned service connection.",
        boundary: "Workload identity"
      }
    ];
    return pageHeader(page, pageId, common) +
      boundary(page.note) +
      '<section class="kw-priority" aria-labelledby="knowledge-priority-title"><div><span class="kw-kicker">Current decision</span>' +
      '<h2 id="knowledge-priority-title">Repository knowledge requires integration setup</h2>' +
      '<p>Documents can use the governed ingestion path. Repository sources remain unavailable until a server-owned connector records authorization and scope.</p></div>' +
      '<a class="kw-button is-primary" href="settings-integrations.html">Review Integration settings</a></section>' +
      '<dl class="kw-metrics" aria-label="Knowledge source structure"><div><dt>Source routes</dt><dd><strong>4</strong><small>one managed, three connectors</small></dd></div>' +
      '<div><dt>Managed upload</dt><dd><strong>1</strong><small>collection-scoped preview</small></dd></div>' +
      '<div><dt>Setup required</dt><dd><strong>3</strong><small>repository connectors</small></dd></div>' +
      '<div><dt>Browser credentials</dt><dd><strong>None</strong><small>server-owned boundary</small></dd></div></dl>' +
      '<section class="kw-section" aria-labelledby="knowledge-source-list"><header class="kw-section-head"><div>' +
      '<span class="kw-kicker">Source catalog</span><h2 id="knowledge-source-list">Choose a governed source</h2>' +
      '<p>Every route keeps connection, freshness, coverage, and authority distinct.</p></div><span>4 source routes</span></header>' +
      '<div class="kw-source-list">' + sourceRows.map(function (source) {
        return '<a class="kw-source-row" href="' + source.href + '"><span class="kw-source-name"><strong>' +
          escapeHtml(source.title) + "</strong><small>" + escapeHtml(source.kind) + '</small></span><span class="kw-source-summary">' +
          escapeHtml(source.summary) + '</span><span class="kw-source-boundary"><small>Boundary</small><strong>' +
          escapeHtml(source.boundary) + "</strong></span>" + status(source.state, source.tone) +
          '<span class="kw-source-open" aria-hidden="true">Open</span></a>';
      }).join("") + "</div></section>" +
      '<section class="kw-section kw-contract" aria-labelledby="retrieval-contract-title"><header class="kw-section-head"><div>' +
      '<span class="kw-kicker">Retrieval contract</span><h2 id="retrieval-contract-title">Evidence stays attributable</h2>' +
      '<p>Knowledge improves grounding; it never grants approval or execution authority.</p></div></header>' +
      '<dl class="kw-facts"><div><dt>Purpose</dt><dd>Evidence-grounded operator answers</dd></div>' +
      '<div><dt>Authorization</dt><dd>Source and collection scoped</dd></div><div><dt>Freshness</dt><dd>Reported per observation</dd></div>' +
      '<div><dt>Incomplete coverage</dt><dd>Explicitly unavailable</dd></div><div><dt>Execution authority</dt><dd>None</dd></div>' +
      '<div><dt>Provenance</dt><dd>Revision and digest retained</dd></div></dl></section>';
  }

  function renderSetup(source) {
    return '<div class="kw-empty-state"><div>' + status("Setup required", "warning") +
      '<h2>' + escapeHtml(source.title) + ' connection is not configured</h2>' +
      '<p>This deployment does not expose a server-owned ' + escapeHtml(source.title) +
      ' connector contract yet. No repository content has been synchronized or indexed from this source.</p>' +
      '<div class="kw-actions"><a class="kw-button is-primary" href="settings-integrations.html">Open Integration settings</a>' +
      '<a class="kw-button" href="knowledge.html">Back to Knowledge</a></div></div>' +
      '<ol class="kw-readiness" aria-label="Connector readiness"><li class="is-current"><span>1</span><div><strong>Configure integration</strong>' +
      '<small>Provider identity and secret custody are not recorded.</small></div></li><li><span>2</span><div><strong>Authorize scope</strong>' +
      '<small>Repository and ref allowlists are not recorded.</small></div></li><li><span>3</span><div><strong>Observe synchronization</strong>' +
      '<small>No freshness or coverage evidence exists.</small></div></li></ol></div>';
  }

  function renderChecking(source) {
    return '<div class="kw-state-message" role="status"><div>' + status("Checking", "info") +
      '<h2>Checking ' + escapeHtml(source.title) + ' connector status</h2>' +
      '<p>The preview is showing a bounded loading state. Existing evidence remains unchanged while a server-owned status read is pending.</p></div>' +
      '<div class="kw-skeleton" aria-hidden="true"><span></span><span></span><span></span></div></div>';
  }

  function renderError(source) {
    return '<div class="kw-state-message"><div>' + status("Status unavailable", "danger") +
      '<h2>Connector status could not be read</h2><p>The last successful ' + escapeHtml(source.title) +
      ' observation is not substituted for the failed read. Retry remains a preview-only interaction.</p>' +
      '<div class="kw-actions"><button class="kw-button is-primary" type="button" data-kw-retry>Retry preview</button>' +
      '<a class="kw-button" href="knowledge.html">Back to Knowledge</a></div></div>' +
      '<dl class="kw-state-facts"><div><dt>Displayed evidence</dt><dd>Unavailable</dd></div>' +
      '<div><dt>Cached success</dt><dd>Not substituted</dd></div><div><dt>Action authority</dt><dd>None</dd></div></dl></div>';
  }

  function renderRepositoryDetail(source, recordId) {
    var record = source.records.find(function (candidate) { return candidate.id === recordId; }) || source.records[0];
    return '<header class="kw-detail-head"><div><span class="kw-kicker">Selected repository</span><h3>' +
      escapeHtml(record.name) + '</h3><p>Connected-state sample only. Values are illustrative and do not represent a live provider read.</p></div>' +
      status(record.freshness, record.tone) + '</header><dl class="kw-facts"><div><dt>Authorized ref</dt><dd><code>' +
      escapeHtml(record.ref) + "</code></dd></div><div><dt>Authorization</dt><dd>" +
      escapeHtml(record.authorization) + "</dd></div><div><dt>Coverage</dt><dd>" +
      escapeHtml(record.coverage) + "</dd></div><div><dt>Last observation</dt><dd>" +
      (record.observed.indexOf("T") > -1 ? '<time datetime="' + escapeHtml(record.observed) + '">' + escapeHtml(record.observed) + "</time>" : escapeHtml(record.observed)) +
      "</dd></div><div><dt>Observation receipt</dt><dd><code>" + escapeHtml(record.receipt) +
      "</code></dd></div><div><dt>Mutation authority</dt><dd>None</dd></div></dl>";
  }

  function renderConnected(source) {
    return '<div class="kw-connected-note" role="note"><strong>Illustrative connected state.</strong>' +
      '<span>No live provider request was made. Repository names and observations are synthetic.</span></div>' +
      '<div class="kw-repository-tools"><label for="kw-repository-search">Filter repositories</label>' +
      '<input id="kw-repository-search" type="search" placeholder="Repository or authorized ref" data-kw-repository-search />' +
      '<span role="status" aria-live="polite" data-kw-repository-count>' + source.records.length + " of " +
      source.records.length + ' repositories</span></div><div class="kw-repository-workspace"><div class="kw-repository-list" aria-label="' +
      escapeHtml(source.title) + ' repositories">' + source.records.map(function (record, index) {
        return '<button class="kw-repository-option" type="button" data-kw-repository="' +
          escapeHtml(record.id) + '" aria-pressed="' + (index === 0 ? "true" : "false") +
          '"><span><strong>' + escapeHtml(record.name) + '</strong><small><code>' +
          escapeHtml(record.ref) + "</code> - " + escapeHtml(record.coverage) + "</small></span>" +
          status(record.freshness, record.tone) + "</button>";
      }).join("") + '</div><article class="kw-repository-detail" data-kw-repository-detail>' +
      renderRepositoryDetail(source, source.records[0].id) + '</article><p class="kw-no-results" data-kw-repository-empty hidden>No repositories match this filter. Clear the filter to restore the connected sample.</p></div>';
  }

  function renderConnectorState(source, state) {
    if (state === "checking") return renderChecking(source);
    if (state === "connected") return renderConnected(source);
    if (state === "error") return renderError(source);
    return renderSetup(source);
  }

  function renderConnector(page, pageId, common) {
    var source = sources[page.sourceId];
    return pageHeader(page, pageId, common) +
      boundary(page.note) +
      '<section class="kw-state-stage" aria-labelledby="connector-state-title"><header class="kw-state-head"><div>' +
      '<span class="kw-kicker">Connection readiness</span><h2 id="connector-state-title">Review the ' +
      escapeHtml(source.title) + ' knowledge boundary</h2><p>The default reflects the current Console contract. Other choices are explicitly synthetic state specimens.</p></div>' +
      '<label class="kw-state-picker" for="kw-connector-state"><span>Specimen state</span><select id="kw-connector-state" data-kw-connector-state>' +
      '<option value="setup">Setup required (default)</option><option value="checking">Checking status</option>' +
      '<option value="connected">Connected sample</option><option value="error">Status unavailable</option></select></label></header>' +
      '<div class="kw-state-region" tabindex="-1" aria-live="polite" data-kw-state-region>' +
      renderSetup(source) + "</div></section>" +
      '<section class="kw-section kw-contract" aria-labelledby="connector-boundary-title"><header class="kw-section-head"><div>' +
      '<span class="kw-kicker">Authority boundary</span><h2 id="connector-boundary-title">Connection facts</h2>' +
      '<p>Setup must complete through a server-owned integration before repository evidence is usable.</p></div></header>' +
      '<dl class="kw-facts"><div><dt>Provider</dt><dd>' + escapeHtml(source.title) + "</dd></div>" +
      "<div><dt>Identity model</dt><dd>" + escapeHtml(source.identity) + "</dd></div>" +
      "<div><dt>Scope contract</dt><dd>" + escapeHtml(source.scope) + "</dd></div>" +
      "<div><dt>Integration owner</dt><dd>" + escapeHtml(source.integration) + "</dd></div>" +
      '<div><dt>Browser credentials</dt><dd>Never stored</dd></div><div><dt>Execution authority</dt><dd>None</dd></div></dl>' +
      '<details class="kw-disclosure"><summary>What becomes available after setup</summary><div>' +
      '<p>Authorized repositories can expose exact refs, observation time, freshness, indexed coverage, and a durable retrieval receipt.</p>' +
      '<ul><li>Unavailable and stale observations remain distinct from zero results.</li>' +
      '<li>Repository content stays inside the configured provider and path scope.</li>' +
      '<li>Knowledge retrieval never grants approval or managed-resource execution authority.</li></ul></div></details></section>';
  }

  function setRepositorySelection(root, source, recordId) {
    root.querySelectorAll("[data-kw-repository]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-kw-repository") === recordId));
    });
    var detail = root.querySelector("[data-kw-repository-detail]");
    if (detail) detail.innerHTML = renderRepositoryDetail(source, recordId);
  }

  function filterRepositories(root, source) {
    var input = root.querySelector("[data-kw-repository-search]");
    if (!input) return;
    var query = input.value.trim().toLocaleLowerCase();
    var visible = [];
    root.querySelectorAll("[data-kw-repository]").forEach(function (button) {
      var record = source.records.find(function (candidate) {
        return candidate.id === button.getAttribute("data-kw-repository");
      });
      var match = Boolean(record) && (!query || (record.name + " " + record.ref).toLocaleLowerCase().includes(query));
      button.hidden = !match;
      if (match) visible.push(button);
    });
    var count = root.querySelector("[data-kw-repository-count]");
    if (count) count.textContent = visible.length + " of " + source.records.length + " repositories";
    var empty = root.querySelector("[data-kw-repository-empty]");
    var detail = root.querySelector("[data-kw-repository-detail]");
    if (empty) empty.hidden = visible.length > 0;
    if (detail) detail.hidden = visible.length === 0;
    if (visible.length > 0 && !visible.some(function (button) {
      return button.getAttribute("aria-pressed") === "true";
    })) {
      setRepositorySelection(root, source, visible[0].getAttribute("data-kw-repository"));
    }
  }

  function bindConnector(root, source) {
    root.addEventListener("change", function (event) {
      if (!event.target.matches("[data-kw-connector-state]")) return;
      var region = root.querySelector("[data-kw-state-region]");
      region.setAttribute("aria-busy", String(event.target.value === "checking"));
      region.innerHTML = renderConnectorState(source, event.target.value);
    });
    root.addEventListener("input", function (event) {
      if (event.target.matches("[data-kw-repository-search]")) filterRepositories(root, source);
    });
    root.addEventListener("click", function (event) {
      var repository = event.target.closest("[data-kw-repository]");
      if (repository) {
        setRepositorySelection(root, source, repository.getAttribute("data-kw-repository"));
        return;
      }
      if (!event.target.closest("[data-kw-retry]")) return;
      var picker = root.querySelector("[data-kw-connector-state]");
      var region = root.querySelector("[data-kw-state-region]");
      picker.value = "checking";
      region.setAttribute("aria-busy", "true");
      region.innerHTML = renderChecking(source);
      region.focus();
      window.setTimeout(function () {
        picker.value = "setup";
        region.setAttribute("aria-busy", "false");
        region.innerHTML = renderSetup(source);
      }, 350);
    });
  }

  function mount(root, page, pageId, common) {
    document.title = page.title + " - FDAI Console";
    root.id = "knowledge-main";
    root.setAttribute("tabindex", "-1");
    root.innerHTML = page.variant === "overview"
      ? renderOverview(page, pageId, common)
      : renderConnector(page, pageId, common);
    if (page.variant === "connector") bindConnector(root, sources[page.sourceId]);
  }

  window.FDAI_KNOWLEDGE_RENDERER = { mount: mount };
})();
