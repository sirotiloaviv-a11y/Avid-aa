// @ts-check
// A deliberately small Markdown renderer that builds DOM nodes with
// textContent only. Model output is never parsed as HTML and never executed.
// Every block gets dir="auto" so Hebrew and English paragraphs each take
// their own direction; code is always left-to-right.

const SAFE_URL = /^(https?:|mailto:)/i;

/**
 * @param {string} tag
 * @param {Record<string, string>} [attrs]
 * @param {(Node|string)[]} [children]
 * @returns {HTMLElement}
 */
export function h(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const c of children) el.append(c);
  return el;
}

/**
 * Inline formatting: `code`, **bold**, *italic* / _italic_, [text](url).
 * @param {string} text
 * @returns {Node[]}
 */
export function renderInline(text) {
  /** @type {Node[]} */
  const out = [];
  const re = /(`+)([\s\S]*?[^`])\1(?!`)|\*\*([^*]+?)\*\*|__([^_]+?)__|\*([^*\s][^*]*?)\*|(?<![\w֐-׿])_([^_\s][^_]*?)_(?![\w֐-׿])|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
    if (m[2] !== undefined) {
      out.push(h("code", { dir: "ltr" }, [m[2].trim() || m[2]]));
    } else if (m[3] !== undefined || m[4] !== undefined) {
      out.push(h("strong", {}, renderInline(m[3] ?? m[4])));
    } else if (m[5] !== undefined || m[6] !== undefined) {
      out.push(h("em", {}, renderInline(m[5] ?? m[6])));
    } else if (m[7] !== undefined) {
      const url = m[8];
      if (SAFE_URL.test(url)) {
        out.push(
          h("a", { href: url, target: "_blank", rel: "noopener noreferrer nofollow" }, renderInline(m[7])),
        );
      } else {
        out.push(document.createTextNode(m[0]));
      }
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

/**
 * @param {string} code
 * @param {string} lang
 * @param {{copy: string, copied: string}} labels
 */
function codeBlock(code, lang, labels) {
  const btn = h("button", { type: "button", class: "code-copy" }, [labels.copy]);
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code);
      btn.textContent = labels.copied;
      setTimeout(() => (btn.textContent = labels.copy), 1500);
    } catch {
      /* clipboard unavailable: leave the button as is */
    }
  });
  const header = h("div", { class: "code-header" }, [h("span", { class: "code-lang" }, [lang || "text"]), btn]);
  const pre = h("pre", { dir: "ltr", tabindex: "0" }, [h("code", {}, [code])]);
  return h("div", { class: "code-block", dir: "ltr" }, [header, pre]);
}

/** @param {string} line */
function splitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

/**
 * @param {string} text
 * @param {{copy: string, copied: string}} labels
 * @returns {DocumentFragment}
 */
export function renderMarkdown(text, labels) {
  const frag = document.createDocumentFragment();
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  /** @type {string[]} */
  let para = [];

  const flushPara = () => {
    if (!para.length) return;
    const p = h("p", { dir: "auto" });
    para.forEach((l, idx) => {
      if (idx) p.append(h("br"));
      p.append(...renderInline(l));
    });
    frag.append(p);
    para = [];
  };

  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*(```+|~~~+)\s*([\w+#.-]*)/);
    if (fence) {
      flushPara();
      const marker = fence[1];
      const body = [];
      i++;
      // An unterminated fence (still streaming) runs to the end of the text.
      while (i < lines.length && !lines[i].trim().startsWith(marker)) body.push(lines[i++]);
      i++;
      frag.append(codeBlock(body.join("\n"), fence[2], labels));
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushPara();
      const level = Math.min(heading[1].length + 1, 6); // h1 is reserved for the page
      frag.append(h(`h${level}`, { dir: "auto" }, renderInline(heading[2])));
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flushPara();
      frag.append(h("hr"));
      i++;
      continue;
    }
    if (/^\s*>/.test(line)) {
      flushPara();
      const quoted = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s*>\s?/, ""));
      frag.append(h("blockquote", { dir: "auto" }, [renderMarkdown(quoted.join("\n"), labels)]));
      continue;
    }
    const listMatch = line.match(/^\s*([-*+]|\d+[.)])\s+/);
    if (listMatch) {
      flushPara();
      const ordered = /\d/.test(listMatch[1]);
      const list = h(ordered ? "ol" : "ul", { dir: "auto" });
      const itemRe = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/;
      while (i < lines.length) {
        const item = lines[i].match(itemRe);
        if (item) {
          list.append(h("li", { dir: "auto" }, renderInline(item[1])));
          i++;
        } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && list.lastElementChild) {
          // continuation line of the previous item
          list.lastElementChild.append(h("br"), ...renderInline(lines[i].trim()));
          i++;
        } else {
          break;
        }
      }
      frag.append(list);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flushPara();
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      const table = h("table", { dir: "auto" }, [
        h("thead", {}, [h("tr", {}, head.map((c) => h("th", { dir: "auto" }, renderInline(c))))]),
        h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", { dir: "auto" }, renderInline(c)))))),
      ]);
      frag.append(h("div", { class: "table-wrap" }, [table]));
      continue;
    }
    if (!line.trim()) {
      flushPara();
      i++;
      continue;
    }
    para.push(line);
    i++;
  }
  flushPara();
  return frag;
}
