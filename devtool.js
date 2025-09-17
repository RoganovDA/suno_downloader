(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const uuidRe = /\/song\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(?:$|[/?#])/i;

  // id -> record
  const songs = new Map(); // { id, url, title, seenInDom, firstSeenAt }
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();

  const now = () => Date.now();

  function upsert(id, url) {
    let r = songs.get(id);
    if (!r) {
      r = { id, url, title: 'Untitled', seenInDom: false, firstSeenAt: now() };
      songs.set(id, r);
    }
    return r;
  }

  function guessTitle(link) {
    const t1 = norm(link.textContent);
    if (t1) return t1;
    const card = link.closest('[role="listitem"], article, li, [class*="card"], [class*="tile"], div');
    if (card) {
      for (const sel of ['[data-testid*="title"]','[class*="title"]','h1,h2,h3,h4','a[title]','[aria-label]','span']) {
        const el = card.querySelector(sel);
        const txt = norm(el?.textContent);
        if (txt && !uuidRe.test(txt)) return txt;
      }
    }
    const aria = link.getAttribute('aria-label');
    if (aria) return norm(aria);
    return 'Untitled';
  }

  function collectOnce() {
    const links = Array.from(document.querySelectorAll('a[href*="/song/"]'));
    let added = 0;
    for (const a of links) {
      const href = a.getAttribute('href') || '';
      const m = href.match(uuidRe);
      if (!m) continue;
      const id = m[1].toLowerCase();
      const url = new URL(href, location.origin).toString();
      const rec = upsert(id, url);
      const t = guessTitle(a);
      if (t && rec.title === 'Untitled') rec.title = t;
      rec.seenInDom = true;
      if (!added && !songs.has(id)) added++;
    }
    return added;
  }

  function getScrollContainer() {
    const cands = [
      '[data-radix-scroll-area-viewport]',
      '[class*="ScrollArea"] [class*="Viewport"]',
      '[class*="scroll"], [class*="Scroll"]',
      'main', '#root', 'body'
    ];
    for (const sel of cands) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return document.scrollingElement || document.body;
  }

  function getTop(sc){ return (sc===document.body||sc===document.scrollingElement) ? window.scrollY : sc.scrollTop; }
  function setTop(sc,y){ (sc===document.body||sc===document.scrollingElement) ? window.scrollTo(0,y) : (sc.scrollTop=y); }
  function maxTop(sc){
    const h = (sc===document.body||sc===document.scrollingElement) ? document.body.scrollHeight : sc.scrollHeight;
    const ch = (sc===document.body||sc===document.scrollingElement) ? window.innerHeight : sc.clientHeight;
    return Math.max(0, h - ch);
  }

  function getTotalFromFooter() {
    const allDivs = document.querySelectorAll('div');
    for (const d of allDivs) {
      const t = norm(d.textContent);
      if (/^\d+\s+songs$/.test(t)) {
        const num = parseInt(t, 10);
        if (Number.isFinite(num)) return num;
      }
    }
    return null;
  }

  // перехватываем JSON, но НЕ засчитываем их в итог, если не seenInDom
  (function hookNetwork(){
    const addFromText = (txt) => {
      const re = /(?:\/song\/|["'](?:id|songId|songUUID)["']\s*:\s*["'])([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})/ig;
      let m;
      while ((m = re.exec(txt))) {
        const id = m[1].toLowerCase();
        upsert(id, `${location.origin}/song/${id}`);
      }
    };

    const _fetch = window.fetch;
    window.fetch = async (...args) => {
      const res = await _fetch(...args);
      try {
        const clone = res.clone();
        const ct = clone.headers.get('content-type')||'';
        if (ct.includes('application/json')) {
          const text = await clone.text();
          addFromText(text);
        }
      } catch {}
      return res;
    };

    const _open = XMLHttpRequest.prototype.open;
    const _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(...a){ this._url = a[1]; return _open.apply(this,a); };
    XMLHttpRequest.prototype.send = function(...a){
      this.addEventListener('load', function(){
        try {
          const ct = this.getResponseHeader('content-type')||'';
          if (ct.includes('application/json')) {
            (this.responseText) && addFromText(this.responseText);
          }
        } catch {}
      });
      return _send.apply(this,a);
    };
  })();

  // ---- прокрутка вниз мелкими шагами до футера/застоя
  collectOnce();
  const sc = getScrollContainer();
  const viewport = (sc===document.body||sc===document.scrollingElement) ? window.innerHeight : sc.clientHeight;
  const step = Math.max(200, Math.floor(viewport * 0.7));
  let idle = 0, prev = -1;

  const observer = new MutationObserver(() => collectOnce());
  observer.observe(document.body, { childList:true, subtree:true });

  for (let i = 0; i < 2000; i++) {
    const before = [...songs.values()].filter(s => s.seenInDom).length;
    const target = getTotalFromFooter();
    if (target != null && before >= target) break;

    const next = Math.min(maxTop(sc), getTop(sc) + step);
    setTop(sc, next);
    await sleep(450);
    collectOnce();

    const after = [...songs.values()].filter(s => s.seenInDom).length;
    if (after === before && after === prev) idle++; else idle = 0;
    prev = after;

    if (idle >= 6) break;
    if (next >= maxTop(sc) - 1) {
      await sleep(800);
      collectOnce();
      const t2 = getTotalFromFooter();
      if (t2 != null && [...songs.values()].filter(s => s.seenInDom).length >= t2) break;
    }
  }
  observer.disconnect();

  // ---- догружаем тайтлы для Untitled запросами на /song/<id>
  const needTitles = [...songs.values()].filter(r => r.seenInDom && (!r.title || r.title === 'Untitled'));
  async function fetchTitleHtml(url) {
    try {
      const res = await fetch(url, { credentials: 'include' });
      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const og = doc.querySelector('meta[property="og:title"]')?.getAttribute('content');
      const docTitle = doc.querySelector('title')?.textContent;
      const h1 = doc.querySelector('h1,h2,h3,[data-testid*="title"]')?.textContent;
      return norm(og || h1 || docTitle || '');
    } catch {
      return '';
    }
  }
  async function pMapLimit(items, limit, worker) {
    const ret = [];
    let i = 0;
    const run = async () => {
      while (i < items.length) {
        const idx = i++;
        ret[idx] = await worker(items[idx], idx);
        await sleep(100); // лёгкая разрядка
      }
    };
    await Promise.all(Array.from({length: limit}, run));
    return ret;
  }
  await pMapLimit(needTitles, 4, async (rec) => {
    const t = await fetchTitleHtml(rec.url);
    if (t) rec.title = t;
  });

  // ---- вычисляем итоговый набор: только seenInDom; если есть footer N — обрезаем до N по порядку появления
  const visible = [...songs.values()]
    .filter(r => r.seenInDom)
    .sort((a,b) => a.firstSeenAt - b.firstSeenAt);

  const expected = getTotalFromFooter();
  const finalList = expected ? visible.slice(0, expected) : visible;

  console.log(`Итог: найдено в DOM ${visible.length}${expected ? `, ожидается ${expected}` : ''}. К экспорту: ${finalList.length}.`);

  // ---- экспорт CSV/TSV/JSON с BOM-дружелюбием
  (function exportAll(list) {
    const rows = [['id','url','title']];
    for (const r of list) rows.push([r.id, r.url, r.title || 'Untitled']);

    const escCSV = (s) => `"${String(s).replace(/"/g, '""')}"`;
    const csv = rows.map(r => r.map(escCSV).join(',')).join('\n');
    downloadBlob('\uFEFF' + csv, 'text/csv;charset=utf-8', 'suno_songs.csv');

    const escTSV = (s) => String(s).replace(/\t/g,' ').replace(/\r?\n/g,' ');
    const tsv = rows.map(r => r.map(escTSV).join('\t')).join('\n');
    downloadBlob('\uFEFF' + tsv, 'text/tab-separated-values;charset=utf-8', 'suno_songs.tsv');

    const json = JSON.stringify(list.map(({id,url,title}) => ({id,url,title})), null, 2);
    downloadBlob(json, 'application/json;charset=utf-8', 'suno_songs.json');

    function downloadBlob(data, mime, filename) {
      const blob = new Blob([data], { type: mime });
      const dl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = dl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(dl);
    }
  })(finalList);
})();
