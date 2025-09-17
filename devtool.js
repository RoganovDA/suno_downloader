(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const uuidRe = /\/song\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(?:$|[/?#])/i;
  const songs = new Map();
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();

  function guessTitle(link) {
    const t1 = norm(link.textContent);
    if (t1) return t1;
    const card = link.closest('[role="listitem"], article, li, [class*="card"], [class*="tile"], div');
    if (card) {
      for (const sel of ['[data-testid*="title"]','[class*="title"]','h3,h4','a[title]','[aria-label]','span']) {
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
      if (!songs.has(id)) {
        const url = new URL(href, location.origin).toString();
        const title = guessTitle(a);
        songs.set(id, { id, url, title });
        added++;
      }
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

  function scrollToBottom(sc) {
    if (sc === document.body || sc === document.scrollingElement) {
      window.scrollTo(0, document.body.scrollHeight);
    } else {
      sc.scrollTop = sc.scrollHeight;
    }
  }

  function getTotalFromFooter() {
    const footer = Array.from(document.querySelectorAll('div'))
      .find(d => /songs$/.test(norm(d.textContent)));
    if (!footer) return null;
    const num = parseInt(footer.textContent);
    return Number.isFinite(num) ? num : null;
  }

  async function scrollUntilCountMatches(maxLoops = 400) {
    const sc = getScrollContainer();
    let loops = 0;
    let targetTotal = null;
    while (loops < maxLoops) {
      collectOnce();
      targetTotal = getTotalFromFooter();
      if (targetTotal && songs.size >= targetTotal) break;
      scrollToBottom(sc);
      await sleep(800);
      loops++;
    }
    return targetTotal;
  }

  console.log('▶ Начинаем сбор треков...');
  collectOnce();

  const expected = await scrollUntilCountMatches();
  const total = songs.size;
  console.log(`✅ Собрано треков: ${total}${expected ? ` / ожидается: ${expected}` : ''}`);
  if (expected && total < expected) {
    console.warn(`⚠ Собрано меньше, чем ожидается. Прокрутите руками ещё раз вниз и перезапустите.`);
  }

  // Формируем CSV
  const rows = [['id','url','title']];
  for (const {id,url,title} of songs.values()) {
    const esc = s => `"${String(s).replace(/"/g,'""')}"`;
    rows.push([esc(id), esc(url), esc(title)].join(','));
  }
  const csv = rows.join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const dl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = dl;
  a.download = 'suno_songs.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(dl);
})();
