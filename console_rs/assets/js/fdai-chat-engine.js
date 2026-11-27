/* FDAI Console v4 — Unified High-Speed Streaming Chat Engine, Trajectory Inspector & XSS-Safe Markdown Renderer.
   Shared by both the dedicated /chat 3-pane Command Deck and the global right chat sidebar across all 65 panels.
   Invariants:
   - Zero innerHTML / outerHTML for untrusted/API content (pure createElement + textContent).
   - User questions: subtle neutral fill; Agent replies: completely transparent (no card/box background).
   - Zero colored left/top accent borders/rails.
   - ChatGPT-smooth requestAnimationFrame high-speed token streaming + skeleton pre-render before first token.
   - Full Trajectory visibility down to executed ontology SQL queries and assembled grounding/system/user prompts. */
(function () {
  "use strict";

  const MAX_PROMPT_CHARS = 4096;
  const MAX_SSE_BUFFER_CHARS = 512 * 1024;

  function safeInternalHref(raw, fallback) {
    const fb = fallback || "/overview/dashboard";
    const s = String(raw || "").trim();
    if (!s || !s.startsWith("/") || s.startsWith("//") || /[\u0000-\u001f\u007f]/.test(s)) {
      return fb;
    }
    return s;
  }

  function safeAssetSrc(raw, fallback) {
    const fb = fallback || "/agent-icons/bragi.svg";
    const s = String(raw || "").trim();
    if (
      !s ||
      s.includes("..") ||
      /[\u0000-\u001f\u007f]/.test(s) ||
      (!s.startsWith("/agent-icons/") && !s.startsWith("/azure-icons/")) ||
      (!s.endsWith(".svg") && !s.endsWith(".png"))
    ) {
      return fb;
    }
    return s;
  }

  function preferReducedMotion() {
    return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs && typeof attrs === "object") {
      Object.entries(attrs).forEach(([k, v]) => {
        if (v === null || v === undefined || v === false) return;
        if (k === "className") node.className = String(v);
        else if (k === "hidden") node.hidden = Boolean(v);
        else if (k === "open") node.open = Boolean(v);
        else if (k === "value") node.value = String(v);
        else if (k === "textContent") node.textContent = String(v);
        else if (k === "style" && typeof v === "string") node.setAttribute("style", v);
        else if (v === true) node.setAttribute(k, "");
        else node.setAttribute(k, String(v));
      });
    }
    if (children !== undefined && children !== null) {
      const list = Array.isArray(children) ? children : [children];
      list.forEach((child) => {
        if (child === null || child === undefined || child === false) return;
        if (child instanceof Node) node.appendChild(child);
        else node.appendChild(document.createTextNode(String(child)));
      });
    }
    return node;
  }

  function makeBadge(toneClass, text, withDot, extraAttrs) {
    const attrs = Object.assign({ className: `cs-badge ${toneClass || "tone-neutral"}` }, extraAttrs || {});
    return el("span", attrs, [withDot !== false ? el("span", { className: "cs-dot" }) : null, String(text ?? "")]);
  }

  function setBadge(badgeEl, toneClass, text, withDot) {
    if (!badgeEl) return;
    const wantDot = withDot !== false;
    const streaming = badgeEl.classList.contains("fdai-live-streaming");
    badgeEl.className = `cs-badge ${toneClass || "tone-neutral"}${streaming ? " fdai-live-streaming" : ""}`;
    const nodes = [];
    if (wantDot) nodes.push(el("span", { className: "cs-dot" }));
    nodes.push(document.createTextNode(String(text ?? "")));
    badgeEl.replaceChildren(...nodes);
  }

  function buildDeepLink(panelId, itemId) {
    const cleanItem = itemId == null ? "" : String(itemId).trim();
    if (panelId && window.fdaiV4Selection && typeof window.fdaiV4Selection.buildItemUrl === "function") {
      return safeInternalHref(window.fdaiV4Selection.buildItemUrl(panelId, cleanItem), "/overview/dashboard");
    }
    const map = {
      ontology: "/governance/ontology",
      "blast-radius": "/governance/blast-radius",
      rules: "/governance/rules",
      incidents: "/operations/incidents",
      "hil-queue": "/operations/hil-queue",
      live: "/operations/live",
      "conversation-delivery": "/operations/conversation-delivery",
      audit: "/evidence/audit",
      trace: "/evidence/trace",
      "command-deck-chat": "/chat",
    };
    const base = map[panelId] || "/overview/dashboard";
    return cleanItem ? safeInternalHref(`${base}?item=${encodeURIComponent(cleanItem)}`, base) : base;
  }

  function localClockShort(isoOrMs) {
    if (window.fdaiV4Humanize && typeof window.fdaiV4Humanize.localClock === "function") {
      return window.fdaiV4Humanize.localClock(isoOrMs || Date.now()).slice(0, 5);
    }
    const d = isoOrMs ? new Date(isoOrMs) : new Date();
    if (Number.isNaN(d.getTime())) return "--:--";
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function copyWithFeedback(text, btn, defaultLabel) {
    const reset = () => {
      window.setTimeout(() => {
        if (btn) btn.textContent = defaultLabel;
      }, 1300);
    };
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard
        .writeText(String(text || ""))
        .then(() => {
          if (btn) btn.textContent = "복사됨";
          reset();
        })
        .catch(() => {
          if (btn) btn.textContent = "복사 불가";
          reset();
        });
    } else if (btn) {
      btn.textContent = "복사 불가";
      reset();
    }
  }

  const Shimmer = {
    border(n, ms) {
      if (n && window.fdaiV4Shimmer?.border) window.fdaiV4Shimmer.border(n, ms);
    },
    bg(n, ms) {
      if (n && window.fdaiV4Shimmer?.bg) window.fdaiV4Shimmer.bg(n, ms);
    },
    pulse(n, ms) {
      if (n && window.fdaiV4Shimmer?.pulse) window.fdaiV4Shimmer.pulse(n, ms);
    },
    markStreaming(n, on) {
      if (n && window.fdaiV4Shimmer?.markStreaming) window.fdaiV4Shimmer.markStreaming(n, on);
    },
  };

  /* 1. XSS-Safe Inline & Block Markdown Renderer (DOM APIs only) */
  function appendInlineMarkdown(parent, text, onCitationClick) {
    const src = String(text || "");
    const tokenRe = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;
    let lastIdx = 0;
    let match;
    while ((match = tokenRe.exec(src)) !== null) {
      if (match.index > lastIdx) {
        parent.appendChild(document.createTextNode(src.slice(lastIdx, match.index)));
      }
      const tok = match[0];
      if (tok.startsWith("**") && tok.endsWith("**")) {
        parent.appendChild(el("strong", null, tok.slice(2, -2)));
      } else if (tok.startsWith("`") && tok.endsWith("`")) {
        parent.appendChild(el("code", { className: "chat-inline-code" }, tok.slice(1, -1)));
      } else if (tok.startsWith("[") && tok.endsWith("]")) {
        const num = tok.slice(1, -1);
        const chip = el("button", {
          type: "button",
          className: "cite-chip",
          "data-cite-ref": num,
          "aria-label": `근거 출처 ${num} 보기`,
        }, tok);
        if (typeof onCitationClick === "function") {
          chip.addEventListener("click", () => onCitationClick(num));
        }
        parent.appendChild(chip);
      }
      lastIdx = tokenRe.lastIndex;
    }
    if (lastIdx < src.length) {
      parent.appendChild(document.createTextNode(src.slice(lastIdx)));
    }
  }

  function renderMarkdownToNode(container, markdownText, opts) {
    if (!container) return;
    const o = opts || {};
    const raw = String(markdownText || "").replace(/\r\n/g, "\n");
    const lines = raw.split("\n");
    const frag = document.createDocumentFragment();
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();
      if (!trimmed) {
        i += 1;
        continue;
      }

      // Fenced code block ```
      if (trimmed.startsWith("```")) {
        const lang = trimmed.slice(3).trim() || "code";
        const codeLines = [];
        i += 1;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          codeLines.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) i += 1;
        const codeText = codeLines.join("\n");
        const copyBtn = el("button", { type: "button", className: "cs-btn cs-btn-sm chat-code-copy" }, "복사");
        copyBtn.addEventListener("click", () => copyWithFeedback(codeText, copyBtn, "복사"));
        frag.appendChild(
          el("div", { className: "chat-code-block" }, [
            el("div", { className: "chat-code-head" }, [
              el("span", { className: "cell-mono" }, lang),
              copyBtn,
            ]),
            el("pre", null, el("code", null, codeText)),
          ])
        );
        continue;
      }

      // Headings ## / ### / ####
      const headMatch = trimmed.match(/^(#{2,4})\s+(.+)$/);
      if (headMatch) {
        const level = Math.min(4, Math.max(2, headMatch[1].length));
        const hEl = el(`h${level + 1}`, { className: `chat-md-h chat-md-h${level}` });
        appendInlineMarkdown(hEl, headMatch[2], o.onCitationClick);
        frag.appendChild(hEl);
        i += 1;
        continue;
      }

      // Markdown table
      if (trimmed.startsWith("|") && i + 1 < lines.length && /^\|\s*[-:]+/.test(lines[i + 1].trim())) {
        const parseRow = (r) =>
          r
            .trim()
            .replace(/^\|/, "")
            .replace(/\|$/, "")
            .split("|")
            .map((c) => c.trim());
        const headers = parseRow(trimmed);
        i += 2; // skip header + separator
        const bodyRows = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          bodyRows.push(parseRow(lines[i]));
          i += 1;
        }
        const thead = el(
          "thead",
          null,
          el(
            "tr",
            null,
            headers.map((h) => {
              const th = el("th");
              appendInlineMarkdown(th, h, o.onCitationClick);
              return th;
            })
          )
        );
        const tbody = el(
          "tbody",
          null,
          bodyRows.map((row) =>
            el(
              "tr",
              null,
              headers.map((hText, colIdx) => {
                const td = el("td", { "data-label": String(hText || "") });
                appendInlineMarkdown(td, row[colIdx] || "—", o.onCitationClick);
                return td;
              })
            )
          )
        );
        frag.appendChild(el("div", { className: "chat-md-table-wrap" }, el("table", { className: "chat-md-table" }, [thead, tbody])));
        continue;
      }

      // Unordered list
      if (/^[-*]\s+/.test(trimmed)) {
        const ul = el("ul", { className: "chat-md-list" });
        while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
          const li = el("li");
          appendInlineMarkdown(li, lines[i].trim().replace(/^[-*]\s+/, ""), o.onCitationClick);
          ul.appendChild(li);
          i += 1;
        }
        frag.appendChild(ul);
        continue;
      }

      // Ordered list
      if (/^\d+\.\s+/.test(trimmed)) {
        const ol = el("ol", { className: "chat-md-list" });
        while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
          const li = el("li");
          appendInlineMarkdown(li, lines[i].trim().replace(/^\d+\.\s+/, ""), o.onCitationClick);
          ol.appendChild(li);
          i += 1;
        }
        frag.appendChild(ol);
        continue;
      }

      // Paragraph (accumulate consecutive plain lines; guaranteed to consume at least 1 line even on partial streaming tokens)
      const isTableStartAt = (idx) =>
        idx < lines.length &&
        lines[idx].trim().startsWith("|") &&
        idx + 1 < lines.length &&
        /^\|\s*[-:]+/.test(lines[idx + 1].trim());

      const paraLines = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !lines[i].trim().startsWith("```") &&
        !/^(#{2,4})\s+/.test(lines[i].trim()) &&
        !/^[-*]\s+/.test(lines[i].trim()) &&
        !/^\d+\.\s+/.test(lines[i].trim()) &&
        !isTableStartAt(i)
      ) {
        paraLines.push(lines[i].trim());
        i += 1;
      }
      if (!paraLines.length && i < lines.length) {
        paraLines.push(lines[i].trim());
        i += 1;
      }
      const p = el("p");
      appendInlineMarkdown(p, paraLines.join(" "), o.onCitationClick);
      frag.appendChild(p);
    }

    if (o.streaming) {
      const caret = el("span", { className: "chat-stream-caret", "aria-hidden": "true" });
      const lastBlock = frag.lastElementChild;
      if (lastBlock && (lastBlock.tagName === "P" || lastBlock.classList.contains("chat-md-h"))) {
        lastBlock.appendChild(caret);
      } else {
        frag.appendChild(caret);
      }
    }

    container.replaceChildren(frag);
  }

  /* 2. Skeleton Pre-Render Component (neutral shimmer bars before first token) */
  function createAnswerSkeleton() {
    return el("div", { className: "chat-skeleton-wrap", "aria-label": "응답 준비 중", role: "status" }, [
      el("div", { className: "cs-skeleton chat-skel-line", style: "width:84%;height:14px" }),
      el("div", { className: "cs-skeleton chat-skel-line", style: "width:96%;height:14px" }),
      el("div", { className: "cs-skeleton chat-skel-line", style: "width:68%;height:14px" }),
    ]);
  }

  /* 3. ChatGPT-Smooth 60fps High-Speed Token Stream Buffer */
  function createSmoothStreamBuffer(proseNode, scrollerNode, onCitationClick) {
    let targetText = "";
    let displayedLen = 0;
    let rafId = null;
    let active = true;
    let aborted = false;
    let firstChunkReceived = false;
    let lastRenderTs = 0;
    let drainResolvers = [];

    const resolveDrainers = () => {
      const list = drainResolvers;
      drainResolvers = [];
      list.forEach((fn) => {
        try { fn(); } catch (_e) {}
      });
    };

    const scrollIfNearBottom = () => {
      if (!scrollerNode) return;
      const nearBottom = scrollerNode.scrollHeight - scrollerNode.scrollTop - scrollerNode.clientHeight < 180;
      if (nearBottom) scrollerNode.scrollTop = scrollerNode.scrollHeight;
    };

    const advanceStep = (remaining, finishing) => {
      if (preferReducedMotion()) return remaining;
      // ChatGPT-fast buttery cadence (~700-1300 chars/sec at 60fps), never sluggish & never instant-pop
      const minStep = finishing ? 10 : 6;
      const maxStep = finishing ? 24 : 18;
      const proportional = Math.ceil(remaining * (finishing ? 0.14 : 0.18));
      let step = Math.min(remaining, Math.max(minStep, Math.min(maxStep, proportional)));
      // Gently snap forward 1-3 chars to complete a word boundary when near whitespace
      const endPos = displayedLen + step;
      if (endPos < targetText.length) {
        const look = targetText.slice(endPos, endPos + 4);
        const ws = look.search(/[\s\n.,·]/);
        if (ws > 0 && ws <= 3) step += ws;
      }
      return Math.min(remaining, step);
    };

    const renderFrame = (ts) => {
      rafId = null;
      if (aborted) {
        resolveDrainers();
        return;
      }
      const remaining = targetText.length - displayedLen;
      if (remaining > 0) {
        displayedLen += advanceStep(remaining, !active);
        const doneNow = !active && displayedLen >= targetText.length;
        if (!lastRenderTs || ts - lastRenderTs >= 22 || doneNow) {
          lastRenderTs = ts;
          renderMarkdownToNode(proseNode, targetText.slice(0, displayedLen), {
            streaming: !doneNow,
            onCitationClick,
          });
          scrollIfNearBottom();
        }
        if (displayedLen < targetText.length) {
          rafId = window.requestAnimationFrame(renderFrame);
        } else if (!active) {
          renderMarkdownToNode(proseNode, targetText, { streaming: false, onCitationClick });
          scrollIfNearBottom();
          resolveDrainers();
        }
      } else if (!active) {
        if (firstChunkReceived || targetText.length > 0) {
          renderMarkdownToNode(proseNode, targetText, { streaming: false, onCitationClick });
          scrollIfNearBottom();
        }
        resolveDrainers();
      }
    };

    return {
      push(chunk) {
        if (aborted) return;
        const s = String(chunk || "");
        if (!s) return;
        firstChunkReceived = true;
        targetText += s;
        if (!rafId) {
          rafId = window.requestAnimationFrame(renderFrame);
        }
      },
      finish(finalAnswer) {
        active = false;
        if (aborted) return Promise.resolve();
        if (typeof finalAnswer === "string" && finalAnswer.length >= targetText.length) {
          targetText = finalAnswer;
          if (finalAnswer.length > 0) firstChunkReceived = true;
        }
        if (preferReducedMotion() || displayedLen >= targetText.length) {
          if (rafId) {
            window.cancelAnimationFrame(rafId);
            rafId = null;
          }
          displayedLen = targetText.length;
          renderMarkdownToNode(proseNode, targetText, { streaming: false, onCitationClick });
          scrollIfNearBottom();
          resolveDrainers();
          return Promise.resolve();
        }
        return new Promise((resolve) => {
          drainResolvers.push(resolve);
          if (!rafId) {
            rafId = window.requestAnimationFrame(renderFrame);
          }
        });
      },
      abort(fallbackMsg) {
        aborted = true;
        active = false;
        if (rafId) {
          window.cancelAnimationFrame(rafId);
          rafId = null;
        }
        const shown = targetText.slice(0, displayedLen) || fallbackMsg || "";
        renderMarkdownToNode(proseNode, shown, { streaming: false, onCitationClick });
        resolveDrainers();
      },
      getText() {
        return targetText;
      },
      hasContent() {
        return firstChunkReceived;
      },
    };
  }

  /* 4. Detailed Interactive Trajectory Accordion (Ontology SQL Queries + Prompts) */
  function buildCodeDisclosure(label, codeText, metaText) {
    const copyBtn = el("button", { type: "button", className: "cs-btn cs-btn-sm chat-code-copy" }, "복사");
    copyBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      copyWithFeedback(codeText, copyBtn, "복사");
    });
    return el("details", { className: "traj-sub-details" }, [
      el("summary", null, [
        el("span", { className: "traj-sub-label" }, label),
        el("span", { className: "traj-sub-right" }, [
          metaText ? el("span", { className: "cell-mono traj-sub-meta" }, metaText) : null,
          copyBtn,
        ]),
      ]),
      el("pre", { className: "traj-code-pre" }, el("code", null, String(codeText || ""))),
    ]);
  }

  function renderTrajectoryStepNode(step) {
    const num = String(step.step ?? "");
    const title = String(step.title || step.phase || "단계");
    const dur = step.duration_ms != null ? `${step.duration_ms}ms` : "";
    const summary = String(step.summary || "");

    const bodyNodes = [];
    if (summary) {
      bodyNodes.push(el("p", { className: "traj-step-summary" }, summary));
    }

    // Intent & Scope details
    if (step.details && typeof step.details === "object") {
      const d = step.details;
      const pills = [];
      if (d.intent) pills.push(`의도: ${d.intent}`);
      if (d.tier) pills.push(`티어: ${String(d.tier).toUpperCase()}`);
      if (d.mode) pills.push(`모드: ${d.mode === "discussion" ? "에이전트 토론" : "운영자"}`);
      if (Array.isArray(d.keywords) && d.keywords.length) {
        pills.push(`키워드: ${d.keywords.join(", ")}`);
      }
      if (d.policy_guard) {
        pills.push(d.policy_guard === "read_only_mutation_blocked" ? "정책 가드: 변경 차단" : "정책 가드: 조회 전용");
      }
      if (pills.length) {
        bodyNodes.push(
          el(
            "div",
            { className: "traj-pill-row" },
            pills.map((p) => el("span", { className: "traj-pill" }, p))
          )
        );
      }
    }

    // Ontology / Policy / Audit SQL Queries
    if (Array.isArray(step.queries) && step.queries.length) {
      step.queries.forEach((q) => {
        const meta = `${q.row_count ?? 0}건 · ${q.duration_ms ?? 0}ms`;
        bodyNodes.push(
          buildCodeDisclosure(`SQL · ${q.title || q.stage || "온톨로지 조회"}`, q.sql || "", meta)
        );
      });
    }

    // Prompt Assembly (System Prompt + Grounding Context + User Prompt)
    if (step.prompt && typeof step.prompt === "object") {
      const pr = step.prompt;
      const pills = [];
      if (pr.model_route) pills.push(String(pr.model_route));
      if (pr.estimated_tokens) pills.push(`추정 ~${pr.estimated_tokens} 토큰`);
      if (pr.history_turns != null) pills.push(`이전 대화 ${pr.history_turns}턴`);
      if (pills.length) {
        bodyNodes.push(
          el(
            "div",
            { className: "traj-pill-row" },
            pills.map((p) => el("span", { className: "traj-pill" }, p))
          )
        );
      }
      if (pr.system_prompt) {
        bodyNodes.push(buildCodeDisclosure("System Prompt (안전 경계 · 그라운딩 규칙)", pr.system_prompt, "system"));
      }
      if (pr.grounding_context) {
        bodyNodes.push(buildCodeDisclosure("Grounding Context (온톨로지 · 인시던트 실측 주입)", pr.grounding_context, "context"));
      }
      if (pr.user_prompt) {
        bodyNodes.push(buildCodeDisclosure("User Prompt (입력 질의)", pr.user_prompt, "user"));
      }
    }

    return el("div", { className: "traj-step-item", "data-traj-phase": String(step.phase || "") }, [
      el("div", { className: "traj-step-head" }, [
        el("span", { className: "traj-step-left" }, [
          el("span", { className: "traj-step-num" }, num || "•"),
          el("strong", null, title),
        ]),
        dur ? el("span", { className: "cell-mono traj-step-dur" }, dur) : null,
      ]),
      el("div", { className: "traj-step-body" }, bodyNodes),
    ]);
  }

  function createTrajectoryWidget() {
    const stepsMap = new Map();
    const statusDot = el("span", { className: "cs-dot" });
    const titleEl = el("span", { className: "traj-summary-title" }, "추론 · 온톨로지 조회 준비 중…");
    const metaEl = el("span", { className: "traj-summary-meta cell-mono" }, "0/5");
    const listEl = el("div", { className: "traj-steps-list" });
    const detailsEl = el("details", { className: "chat-trajectory", open: false }, [
      el("summary", { className: "chat-trajectory-head" }, [
        el("span", { className: "traj-summary-left" }, [statusDot, titleEl]),
        metaEl,
      ]),
      listEl,
    ]);
    Shimmer.markStreaming(detailsEl, true);

    const recomputeHeader = (completed) => {
      const steps = Array.from(stepsMap.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
      const totalMs = steps.reduce((acc, s) => acc + Number(s.duration_ms || 0), 0);
      const queryCount = steps.reduce((acc, s) => acc + (Array.isArray(s.queries) ? s.queries.length : 0), 0);
      if (completed) {
        detailsEl.classList.add("is-complete");
        Shimmer.markStreaming(detailsEl, false);
        titleEl.textContent = `추론 완료 · ${steps.length}단계 · SQL ${queryCount}건 · 프롬프트`;
        metaEl.textContent = `${totalMs}ms ⌄`;
      } else {
        const latest = steps[steps.length - 1];
        titleEl.textContent = latest ? `${latest.title}…` : "온톨로지 · 근거 조회 중…";
        metaEl.textContent = `${steps.length}/5 · ${totalMs}ms`;
      }
    };

    return {
      el: detailsEl,
      upsertStep(step) {
        if (!step || typeof step !== "object") return;
        const key = String(step.phase || step.step || stepsMap.size);
        stepsMap.set(key, step);
        const ordered = Array.from(stepsMap.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
        listEl.replaceChildren(...ordered.map(renderTrajectoryStepNode));
        recomputeHeader(false);
        Shimmer.bg(detailsEl);
      },
      setAll(steps, completed) {
        if (!Array.isArray(steps) || !steps.length) return;
        stepsMap.clear();
        steps.forEach((s, idx) => {
          stepsMap.set(String(s.phase || s.step || idx), s);
        });
        const ordered = Array.from(stepsMap.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
        listEl.replaceChildren(...ordered.map(renderTrajectoryStepNode));
        recomputeHeader(Boolean(completed));
      },
      complete() {
        recomputeHeader(true);
      },
      getSteps() {
        return Array.from(stepsMap.values()).sort((a, b) => (a.step || 0) - (b.step || 0));
      },
    };
  }

  /* 5. Evidence Block Builder (Discussion + Proposal + Citations + Followups) */
  function buildEvidenceFragment(payload, opts) {
    const o = opts || {};
    const frag = document.createDocumentFragment();
    if (!payload || typeof payload !== "object") return frag;

    if (Array.isArray(payload.agent_discussion) && payload.agent_discussion.length) {
      const grid = el("div", { className: "sse-discussion-grid", "aria-label": "멀티 에이전트 협력 검토" });
      payload.agent_discussion.forEach((d) => {
        grid.appendChild(
          el("div", { className: "sse-discussion-item" }, [
            el("div", { className: "sse-discussion-head" }, [
              el("span", { className: "sse-discussion-agent" }, [
                el("img", { src: safeAssetSrc(d.icon, "/agent-icons/bragi.svg"), alt: "" }),
                String(d.agent || ""),
              ]),
              makeBadge("tone-neutral", String(d.role || ""), false),
            ]),
            el("div", null, String(d.stance || "")),
          ])
        );
      });
      frag.appendChild(grid);
    }

    if (payload.proposal_draft && typeof payload.proposal_draft === "object") {
      const pr = payload.proposal_draft;
      const hilHref = pr.panel_id
        ? buildDeepLink(pr.panel_id, pr.item_id || pr.id)
        : safeInternalHref(pr.href, buildDeepLink("hil-queue", pr.item_id || pr.id));
      const ontHref = buildDeepLink("ontology", pr.target_id || o.selectedNode || "");
      const sgs = Array.isArray(pr.safeguards) ? pr.safeguards : [];
      frag.appendChild(
        el("div", { className: "chat-proposal" }, [
          el("div", { className: "card-head" }, [
            el("strong", { style: "font-size:13px" }, `${pr.title || "조회 전용 검토 초안"} (${pr.id || "검토 초안"})`),
            makeBadge("tone-human", `조회 전용 · ${pr.risk_class || "A3"}`, true),
          ]),
          el("div", { style: "font-size:12.5px;color:var(--cs-text-soft)" }, String(pr.read_only_notice || "")),
          sgs.length
            ? el(
                "div",
                { className: "chat-safeguards-row" },
                sgs.map((sg) => el("span", { className: "safeguard-pill" }, `✓ ${sg}`))
              )
            : null,
          el("div", { className: "toolbar-inline" }, [
            el("a", { className: "cs-btn cs-btn-sm cs-btn-accent", href: hilHref }, "승인 요청 열기 →"),
            el("a", { className: "cs-btn cs-btn-sm", href: ontHref }, "계통 확인 →"),
          ]),
        ])
      );
    }

    if (Array.isArray(payload.citations) && payload.citations.length) {
      const listEl = el("ul", { className: "source-list" });
      payload.citations.forEach((c) => {
        const href = c.panel_id
          ? buildDeepLink(c.panel_id, c.item_id)
          : safeInternalHref(c.href, buildDeepLink("audit", c.item_id));
        listEl.appendChild(
          el("li", { className: "source-list-item", "data-cite-item": String(c.id ?? "") }, [
            el("span", null, [el("strong", null, `[${c.id ?? ""}]`), ` ${c.label || ""}`]),
            el("a", { className: "insp-mini-link", href }, "원본 보기 →"),
          ])
        );
      });
      frag.appendChild(
        el("details", { className: "cs-disclosure", "data-citations-box": "1", style: "width:100%" }, [
          el("summary", null, [
            el("span", null, `근거 출처 (${payload.citations.length}건) · 조회 전용`),
            el("span", { className: "disc-meta" }, payload.measurement_state === "measured" ? "실측 검증됨" : "미측정"),
          ]),
          el("div", { className: "disc-body" }, listEl),
        ])
      );
    }

    if (Array.isArray(payload.followups) && payload.followups.length) {
      const fw = el("div", { className: "chat-followups" });
      payload.followups.forEach((q) => {
        const txt = String(q || "").trim();
        if (!txt) return;
        const chip = el("button", { type: "button", className: "signal-chip", "data-quick-ask": txt }, txt);
        if (typeof o.onQuickAsk === "function") {
          chip.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            o.onQuickAsk(txt);
          });
        }
        fw.appendChild(chip);
      });
      frag.appendChild(fw);
    }

    return frag;
  }

  /* 6. Render a Persisted Turn (on session reload / switching) */
  function renderStoredTurn(container, turn, opts) {
    if (!container || !turn) return;
    const o = opts || {};
    const timeLabel = localClockShort(turn.recorded_at || Date.now());

    container.appendChild(
      el("div", { className: "chat-turn-user", "data-sse-turn": "1" }, [
        el("div", { className: "chat-turn-meta" }, [
          el("span", null, "운영자"),
          el("span", null, `${timeLabel} KST`),
        ]),
        el("div", { className: "chat-bubble-user" }, String(turn.user_message || "")),
      ])
    );

    const traj = createTrajectoryWidget();
    if (Array.isArray(turn.trajectory) && turn.trajectory.length) {
      traj.setAll(turn.trajectory, true);
    } else {
      traj.el.hidden = true;
    }

    const proseWrap = el("div", { className: "agent-prose chat-md" });
    const evidenceWrap = el("div", { "data-sse-evidence": "" });
    const highlightCite = (num) => {
      const det = evidenceWrap.querySelector("[data-citations-box]");
      if (det) {
        det.open = true;
        det.querySelectorAll("[data-cite-item]").forEach((row) => {
          row.classList.toggle("is-highlighted", row.getAttribute("data-cite-item") === String(num));
        });
      }
    };
    renderMarkdownToNode(proseWrap, turn.assistant_answer || "", { streaming: false, onCitationClick: highlightCite });
    evidenceWrap.replaceChildren(
      buildEvidenceFragment(
        {
          measurement_state: turn.measurement_status || "measured",
          citations: turn.citations || [],
          proposal_draft: turn.proposal_draft || null,
          followups: turn.followups || [],
        },
        { selectedNode: turn.selected_node, onQuickAsk: o.onQuickAsk }
      )
    );

    const isMeasured = turn.measurement_status === "measured";
    const srcLabel = turn.source === "postgres-direct" ? "로컬 DB 실측" : isMeasured ? "운영 서비스 실측" : "미측정 · 조회 전용";
    const copyBtn = el("button", { type: "button", className: "cs-btn cs-btn-sm sse-copy-btn" }, "답변 복사");
    copyBtn.addEventListener("click", () => copyWithFeedback(turn.assistant_answer || "", copyBtn, "답변 복사"));

    container.appendChild(
      el("div", { className: "chat-turn-agent", "data-sse-turn": "1" }, [
        el("div", { className: "chat-turn-meta" }, [
          el("span", { className: "chat-agent-id" }, [
            el("img", { src: "/agent-icons/bragi.svg", alt: "", width: "16", height: "16" }),
            el("strong", null, "Bragi"),
          ]),
          makeBadge(isMeasured ? "tone-live" : "tone-human", srcLabel, true),
        ]),
        traj.el,
        proseWrap,
        evidenceWrap,
        el("div", { className: "sse-turn-foot" }, [
          el("span", { className: "chat-turn-meta" }, `${turn.recorded_at_kst || `${timeLabel} KST`}`),
          copyBtn,
        ]),
      ])
    );
  }

  /* 7. Primary Unified Streaming Turn Executor (POST /api/v4/chat/stream) */
  async function streamTurn(params) {
    const p = params || {};
    const rawText = String(p.message || "").trim();
    if (!rawText) return { ok: false, reason: "empty" };
    const text = rawText.length > MAX_PROMPT_CHARS ? rawText.slice(0, MAX_PROMPT_CHARS) : rawText;

    const transcriptEl = p.transcriptEl || document.getElementById("chatTranscriptInner");
    const scrollerEl = p.scrollerEl || document.getElementById("chatTranscript");
    if (!transcriptEl) return { ok: false, reason: "missing_transcript" };

    // Remove welcome/empty placeholder card when first real message is sent
    transcriptEl.querySelectorAll("[data-chat-welcome], [data-chat-empty-state]").forEach((n) => n.remove());

    const nowClock = localClockShort(Date.now());
    const userTurnNodes = [
      el("div", { className: "chat-turn-meta" }, [
        el("span", null, "운영자"),
        el("span", null, `${nowClock} KST`),
      ]),
    ];
    if (Array.isArray(p.attachments) && p.attachments.length) {
      userTurnNodes.push(el("div", { className: "chat-turn-meta" }, `첨부: ${p.attachments.join(", ")}`));
    }
    userTurnNodes.push(el("div", { className: "chat-bubble-user" }, text));
    transcriptEl.appendChild(el("div", { className: "chat-turn-user", "data-sse-turn": "1" }, userTurnNodes));

    const badgeEl = makeBadge("tone-sre", "온톨로지 · 근거 조회 중…", true, { "data-sse-state-badge": "" });
    Shimmer.markStreaming(badgeEl, true);
    Shimmer.pulse(badgeEl);

    const trajWidget = createTrajectoryWidget();
    const proseWrap = el("div", { className: "agent-prose chat-md", "data-sse-prose": "" });
    const skeletonEl = createAnswerSkeleton();
    proseWrap.appendChild(skeletonEl);

    const evidenceEl = el("div", { "data-sse-evidence": "", hidden: true });
    const footEl = el("div", { className: "sse-turn-foot", "data-sse-foot": "", hidden: true });

    const agentTurn = el("div", { className: "chat-turn-agent", "data-sse-turn": "1" }, [
      el("div", { className: "chat-turn-meta" }, [
        el("span", { className: "chat-agent-id" }, [
          el("img", { src: "/agent-icons/bragi.svg", alt: "", width: "16", height: "16" }),
          el("strong", null, "Bragi"),
        ]),
        badgeEl,
      ]),
      trajWidget.el,
      proseWrap,
      evidenceEl,
      footEl,
    ]);
    transcriptEl.appendChild(agentTurn);
    if (scrollerEl) scrollerEl.scrollTop = scrollerEl.scrollHeight;

    const highlightCitation = (num) => {
      const det = evidenceEl.querySelector("[data-citations-box]");
      if (det) {
        det.open = true;
        det.querySelectorAll("[data-cite-item]").forEach((row) => {
          row.classList.toggle("is-highlighted", row.getAttribute("data-cite-item") === String(num));
        });
      }
      if (typeof p.onCitationClick === "function") p.onCitationClick(num);
    };

    const streamBuf = createSmoothStreamBuffer(proseWrap, scrollerEl, highlightCitation);
    const reqBody = {
      message: text,
      session_id: p.sessionId || "active",
      mode: p.mode || "operator",
      tier: p.tier || "auto",
      context: p.context || "AI 채팅",
      selected_node: p.selectedNode || "active-scope",
      busy_mode: p.busyMode || "queue",
      attachments: Array.isArray(p.attachments) ? p.attachments : [],
    };

    let lastMeta = {};
    let lastMeasurement = "not-measured";
    let lastRequestId = "";
    let lastPolicyGuard = "read_only_enforced";
    let resolvedSessionId = reqBody.session_id;
    let firstDeltaSeen = false;
    let pendingDonePayload = null;

    if (p.signal && typeof p.signal.addEventListener === "function") {
      p.signal.addEventListener(
        "abort",
        () => {
          streamBuf.abort();
        },
        { once: true },
      );
    }

    const finalizeTurnUi = (payload) => {
      if (!payload) return;
      trajWidget.complete();

      const finalAns = String(payload.answer || streamBuf.getText());
      const ms = payload.measurement_status || payload.measurement_state || lastMeasurement;
      const guard = String(payload.policy_guard || lastPolicyGuard);
      const reqId = String(payload.request_id || lastRequestId || "");
      const srcName = String(payload.source || "console-v4-rust");
      if (payload.session_id) resolvedSessionId = String(payload.session_id);
      const isMeasured = ms === "measured";
      const isBlocked = guard === "read_only_mutation_blocked";
      const isPgDirect = srcName === "postgres-direct";

      Shimmer.markStreaming(badgeEl, false);
      if (isBlocked) {
        setBadge(badgeEl, "tone-sec", "직접 변경 차단 · 조회 전용", true);
      } else if (isMeasured && isPgDirect) {
        setBadge(badgeEl, "tone-live", "로컬 DB 실측", true);
      } else if (isMeasured) {
        setBadge(badgeEl, "tone-live", "운영 서비스 실측", true);
      } else {
        setBadge(badgeEl, "tone-human", "미측정 · 조회 전용", true);
      }
      Shimmer.pulse(badgeEl);

      if (evidenceEl.childElementCount > 0) {
        evidenceEl.hidden = false;
        evidenceEl.classList.add("chat-reveal-in");
      }

      const copyBtn = el("button", { type: "button", className: "chat-ghost-action sse-copy-btn" }, "복사");
      copyBtn.addEventListener("click", () => copyWithFeedback(finalAns, copyBtn, "복사"));

      const reaskBtn = el("button", { type: "button", className: "chat-ghost-action" }, "다시 질문");
      reaskBtn.addEventListener("click", () => {
        if (typeof p.onQuickAsk === "function") p.onQuickAsk(text);
      });

      const techPanel = el("div", { className: "chat-tech-popover", hidden: true }, [
        el("div", { className: "drawer-tech-list" }, [
          el("div", { className: "drawer-tech-row" }, [el("span", null, "요청 ID"), el("code", null, reqId || "req-chat")]),
          el("div", { className: "drawer-tech-row" }, [el("span", null, "세션 ID"), el("code", null, resolvedSessionId)]),
          el("div", { className: "drawer-tech-row" }, [el("span", null, "데이터 출처"), el("code", null, srcName)]),
          el("div", { className: "drawer-tech-row" }, [el("span", null, "측정 상태"), el("code", null, ms)]),
          el("div", { className: "drawer-tech-row" }, [el("span", null, "정책 경계"), el("code", null, guard)]),
        ]),
      ]);

      const techBtn = el("button", { type: "button", className: "chat-ghost-action", "aria-expanded": "false" }, "기술 상세 ⌄");
      techBtn.addEventListener("click", () => {
        techPanel.hidden = !techPanel.hidden;
        techBtn.setAttribute("aria-expanded", String(!techPanel.hidden));
      });

      footEl.replaceChildren(
        el("div", { className: "chat-action-bar" }, [copyBtn, reaskBtn, techBtn]),
        techPanel
      );
      footEl.hidden = false;
      footEl.classList.add("chat-reveal-in");

      if (typeof p.onEvent === "function") p.onEvent("done", payload);
      window.fdaiTip?.enhance?.(agentTurn);
      if (scrollerEl) scrollerEl.scrollTop = scrollerEl.scrollHeight;
    };

    const handleEvent = (evName, payload) => {
      if (!payload || typeof payload !== "object") return;
      if (evName === "meta") {
        lastMeta = payload;
        lastMeasurement = payload.measurement_status || payload.measurement_state || "not-measured";
        lastRequestId = String(payload.request_id || "");
        lastPolicyGuard = String(payload.policy_guard || "read_only_enforced");
        if (payload.session_id) resolvedSessionId = String(payload.session_id);
        if (typeof p.onEvent === "function") p.onEvent("meta", payload);
      } else if (evName === "trajectory") {
        trajWidget.upsertStep(payload);
        if (payload.phase === "prompt_assembly") {
          setBadge(badgeEl, "tone-sre", "프롬프트 조립 · 답변 생성 중…", true);
        }
        if (typeof p.onEvent === "function") p.onEvent("trajectory", payload);
      } else if (evName === "step") {
        if (typeof p.onEvent === "function") p.onEvent("step", payload);
      } else if (evName === "delta") {
        if (!firstDeltaSeen) {
          firstDeltaSeen = true;
          skeletonEl.remove();
          setBadge(badgeEl, "tone-live", "답변 스트리밍 중…", true);
        }
        streamBuf.push(payload.text || "");
        if (typeof p.onEvent === "function") p.onEvent("delta", payload);
      } else if (evName === "evidence") {
        if (Array.isArray(payload.trajectory) && payload.trajectory.length) {
          trajWidget.setAll(payload.trajectory, true);
        }
        evidenceEl.replaceChildren(
          buildEvidenceFragment(payload, {
            selectedNode: reqBody.selected_node,
            onQuickAsk: p.onQuickAsk,
          })
        );
        evidenceEl.querySelectorAll(".sse-discussion-grid, .chat-proposal, .cs-disclosure").forEach((c) => {
          Shimmer.border(c);
        });
        if (typeof p.onEvent === "function") p.onEvent("evidence", payload);
        window.fdaiTip?.enhance?.(evidenceEl);
      } else if (evName === "done") {
        if (!firstDeltaSeen) {
          firstDeltaSeen = true;
          skeletonEl.remove();
        }
        pendingDonePayload = payload;
      }
    };

    try {
      const resp = await fetch("/api/v4/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(reqBody),
        signal: p.signal,
      });
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        if (buffer.length > MAX_SSE_BUFFER_CHARS) {
          throw new Error("SSE buffer limit exceeded");
        }
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        for (const frame of frames) {
          let evName = "message";
          const dataLines = [];
          for (const rawLine of frame.split(/\r?\n/)) {
            if (rawLine.startsWith("event:")) evName = rawLine.slice(6).trim();
            else if (rawLine.startsWith("data:")) dataLines.push(rawLine.slice(5).trimStart());
          }
          if (dataLines.length) {
            try {
              handleEvent(evName, JSON.parse(dataLines.join("\n")));
            } catch (_e) {
              // Ignore keepalive comments
            }
          }
        }
      }
      if (!firstDeltaSeen) {
        firstDeltaSeen = true;
        skeletonEl.remove();
      }
      const finalAns = String((pendingDonePayload && pendingDonePayload.answer) || streamBuf.getText());
      await streamBuf.finish(finalAns);
      if (pendingDonePayload) {
        finalizeTurnUi(pendingDonePayload);
      } else {
        trajWidget.complete();
        if (evidenceEl.childElementCount > 0) evidenceEl.hidden = false;
      }
      return {
        ok: true,
        sessionId: resolvedSessionId,
        answer: streamBuf.getText(),
        trajectory: trajWidget.getSteps(),
        meta: lastMeta,
      };
    } catch (err) {
      skeletonEl.remove();
      Shimmer.markStreaming(badgeEl, false);
      trajWidget.complete();
      if (err && err.name === "AbortError") {
        setBadge(badgeEl, "tone-neutral", "중단됨", true);
        streamBuf.abort("응답 생성이 사용자 요청으로 중단되었습니다.");
        return { ok: false, aborted: true, sessionId: resolvedSessionId };
      }
      badgeEl.setAttribute("role", "alert");
      setBadge(badgeEl, "tone-sec", "응답 연결 오류 · 미측정", true);
      streamBuf.abort("실시간 응답 채널에 연결하지 못했습니다. 미측정 상태를 유지합니다.");
      return { ok: false, error: String(err), sessionId: resolvedSessionId };
    } finally {
      if (scrollerEl) scrollerEl.scrollTop = scrollerEl.scrollHeight;
    }
  }

  window.fdaiChatEngine = {
    el,
    makeBadge,
    setBadge,
    safeInternalHref,
    safeAssetSrc,
    buildDeepLink,
    localClockShort,
    copyWithFeedback,
    renderMarkdownToNode,
    createAnswerSkeleton,
    createTrajectoryWidget,
    buildEvidenceFragment,
    renderStoredTurn,
    streamTurn,
  };
})();
