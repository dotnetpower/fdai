// Apply issue #36 display terminology at the documentation presentation boundary.
// Canonical terms remain unchanged in code, inline code, raw HTML, URLs, and
// other non-text syntax nodes.

const ENGLISH_REPLACEMENTS = [
  [/\bShadow, then enforce\b/g, "Observe, then enable changes"],
  [/\bHIL decisions\b/gi, "decisions requiring human approval"],
  [/\bHIL decision\b/gi, "decision requiring human approval"],
  [/\bHIL verdicts\b/gi, "decisions requiring human approval"],
  [/\bHIL verdict\b/gi, "decision requiring human approval"],
  [/\bremediation findings\b/gi, "detected issues requiring fixes"],
  [/\bremediation finding\b/gi, "detected issue requiring a fix"],
  [/\bhuman-in-the-loop\s*\(HIL\)/gi, "human approval"],
  [/\bHIL\b/gi, "human approval"],
  [/\bverdicts\b/gi, "decisions"],
  [/\bverdict\b/gi, "decision"],
  [/\bstewardship\b/gi, "operational ownership"],
  [/\bMimir stewards\b/g, "Mimir owns"],
  [/\bstewards\b/gi, "owns"],
  [/\bsteward\b/gi, "accountable owner"],
  [/(?<!FDAI )\bmaintainers\b/gi, "FDAI maintainers"],
  [/(?<!FDAI )\bmaintainer\b/gi, "FDAI maintainer"],
  [/\bbus factor\b/gi, "backup coverage"],
  [/\babstains\b/gi, "holds for review"],
  [/\babstained\b/gi, "held for review"],
  [/\babstain\b/gi, "hold for review"],
  [/\bshadow[- ]mode\b/gi, "observation mode"],
  [/\bshadow-first\b/gi, "observation-first"],
  [/\b(in|to|from) shadow\b/gi, "$1 observation mode"],
  [/\bshadow\b/gi, "observation mode"],
  [/\benforce mode\b/gi, "enforcement mode"],
  [/\blive enforce\b/gi, "live enforcement"],
  [/\benforce (coverage|validation|path)\b/gi, "enforcement $1"],
  [/\b(in|to|from) enforce\b/gi, "$1 enforcement mode"],
  [/\bblast[- ]radius\b/gi, "impact scope"],
  [/\bgrounding\b/gi, "evidence check"],
  [/\bremediations\b/gi, "fixes"],
  [/\bremediation\b/gi, "fix"],
  [/\brisk[- ]gate\b/gi, "safety check"],
  [/\bcapacity findings\b/gi, "capacity issues"],
  [/\bcapacity finding\b/gi, "capacity issue"],
  [/\bfindings\b/gi, "detected issues"],
  [/\bfinding\b/gi, "detected issue"],
  [/(?<!ownership )\bhandover\b/gi, "ownership handover"],
  [/\bAccountable\b/g, "Final owner"],
  [/\bInformed\b/g, "Notified"],
];

const KOREAN_PARTICLES = {
  topic: ["는", "은"],
  subject: ["가", "이"],
  object: ["를", "을"],
  conjunction: ["와", "과"],
  direction: ["로", "으로"],
};

function koreanTerm(pattern, display, hasBatchim) {
  const particles = "은|는|이|가|을|를|과|와|으로|로|의|에";
  return [
    new RegExp(`\\b${pattern}\\b(${particles})?`, "gi"),
    (_match, particle) => {
      if (!particle || particle === "의" || particle === "에") {
        return `${display}${particle ?? ""}`;
      }
      if (particle === "은" || particle === "는") {
        return `${display}${KOREAN_PARTICLES.topic[hasBatchim ? 1 : 0]}`;
      }
      if (particle === "이" || particle === "가") {
        return `${display}${KOREAN_PARTICLES.subject[hasBatchim ? 1 : 0]}`;
      }
      if (particle === "을" || particle === "를") {
        return `${display}${KOREAN_PARTICLES.object[hasBatchim ? 1 : 0]}`;
      }
      if (particle === "과" || particle === "와") {
        return `${display}${KOREAN_PARTICLES.conjunction[hasBatchim ? 1 : 0]}`;
      }
      return `${display}${KOREAN_PARTICLES.direction[hasBatchim ? 1 : 0]}`;
    },
  ];
}

const KOREAN_REPLACEMENTS = [
  [/Shadow, then enforce/gi, "먼저 관찰하고, 검증 후 변경 적용"],
  [/먼저 shadow, 그다음 enforce/gi, "먼저 관찰하고, 검증 후 변경 적용"],
  [/\bShadow\s*모드/gi, "관찰 모드"],
  [/\bEnforce\s*모드/gi, "적용 모드"],
  koreanTerm("HIL decisions?", "사람 승인이 필요한 결정", true),
  koreanTerm("HIL verdicts?", "사람 승인이 필요한 결정", true),
  koreanTerm("remediation findings?", "수정이 필요한 문제", false),
  koreanTerm("human-in-the-loop\\s*\\(HIL\\)", "사람 승인", true),
  koreanTerm("HIL", "사람 승인", true),
  koreanTerm("verdicts?", "결정", true),
  koreanTerm("stewardship", "담당 체계", false),
  koreanTerm("stewards?", "책임 담당자", false),
  koreanTerm("maintainers?", "FDAI 유지관리자", false),
  koreanTerm("bus factor", "담당 가능 인원", true),
  koreanTerm("abstain(?:s|ed)?", "판단 보류", false),
  koreanTerm("shadow[- ]mode", "관찰 모드", false),
  koreanTerm("shadow-first", "관찰 우선", true),
  koreanTerm("shadow", "관찰 모드", false),
  koreanTerm("enforce mode", "적용 모드", false),
  koreanTerm("live enforce", "실제 변경 적용", true),
  [/\benforce (coverage|validation|path)\b/gi, "변경 적용 $1"],
  koreanTerm("blast[- ]radius", "영향 범위", false),
  koreanTerm("grounding", "근거 확인", true),
  koreanTerm("remediations?", "수정", true),
  koreanTerm("risk[- ]gate", "안전성 검토", false),
  koreanTerm("capacity findings?", "용량 문제", false),
  koreanTerm("findings?", "발견된 문제", false),
  koreanTerm("handover", "담당자 인수인계", false),
  koreanTerm("accountable", "최종 책임자", false),
  koreanTerm("informed", "알림 대상", true),
];

function isKoreanDocument(file) {
  const paths = [file?.path, ...(file?.history ?? [])].filter(Boolean);
  return paths.some((path) => /(?:^|[\\/])ko(?:[\\/]|$)|-ko\.md$/i.test(path));
}

function replaceDisplayTerms(value, replacements) {
  return replacements.reduce(
    (current, [pattern, replacement]) => {
      if (typeof replacement !== "string" || replacement.includes("$")) {
        return current.replace(pattern, replacement);
      }
      return current.replace(pattern, (match) => {
        if (!/^[A-Z][a-z]/.test(match) || !/^[a-z]/.test(replacement)) {
          return replacement;
        }
        return replacement[0].toUpperCase() + replacement.slice(1);
      });
    },
    value,
  );
}

function transformMermaidDisplayLabels(value, replacements) {
  const firstLine = value.split("\n").find((line) => line.trim().length > 0) ?? "";
  if (/^timeline\b/i.test(firstLine.trim())) {
    return value
      .split("\n")
      .map((line, index) =>
        index === 0 ? line : replaceDisplayTerms(line, replacements),
      )
      .join("\n");
  }
  if (!/^(flowchart|graph)\b/i.test(firstLine.trim())) return value;

  return value
    .split("\n")
    .map((line) =>
      line
        .replace(/(\[")([^"]*)("\])/g, (_match, open, label, close) =>
          `${open}${replaceDisplayTerms(label, replacements)}${close}`,
        )
        .replace(/(\[)([^\[\]\n]*)(\])/g, (_match, open, label, close) =>
          `${open}${replaceDisplayTerms(label, replacements)}${close}`,
        )
        .replace(/(\{)([^{}\n]*)(\})/g, (_match, open, label, close) =>
          `${open}${replaceDisplayTerms(label, replacements)}${close}`,
        )
        .replace(/(\|)([^|\n]+)(\|)/g, (_match, open, label, close) =>
          `${open}${replaceDisplayTerms(label, replacements)}${close}`,
        ),
    )
    .join("\n");
}

function transformTextNodes(node, replacements) {
  if (node.type === "code" && node.lang === "mermaid") {
    node.value = transformMermaidDisplayLabels(node.value, replacements);
    return;
  }
  if (node.type === "text") {
    node.value = replaceDisplayTerms(node.value, replacements);
    return;
  }

  if (!Array.isArray(node.children)) return;
  for (const child of node.children) transformTextNodes(child, replacements);
}

export function remarkDisplayTerminology() {
  return (tree, file) => {
    const replacements = isKoreanDocument(file)
      ? KOREAN_REPLACEMENTS
      : ENGLISH_REPLACEMENTS;
    const frontmatter = file?.data?.astro?.frontmatter;
    if (frontmatter && typeof frontmatter === "object") {
      for (const key of ["title", "description"]) {
        if (typeof frontmatter[key] === "string") {
          frontmatter[key] = replaceDisplayTerms(frontmatter[key], replacements);
        }
      }
    }
    transformTextNodes(tree, replacements);
  };
}

export default remarkDisplayTerminology;
