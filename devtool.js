(async () => {
  const delay = ms => new Promise(res => setTimeout(res, ms));
  const collected = new Map();

  while (true) {
    document.querySelectorAll('[data-key]').forEach(div => {
      const id = div.getAttribute('data-key');
      if (id?.length === 36) {
        const titleElem = div.querySelector('a[href^="/song/"] > span');
        const title = titleElem ? titleElem.textContent.trim() : 'No title';
        const url = `https://suno.com/song/${id}`;
        collected.set(url, title);
      }
    });

    const nextBtn = Array.from(document.querySelectorAll('button'))
      .find(btn =>
        btn.querySelector('svg path')?.getAttribute('d')?.startsWith('M9 7.343')
      );

    if (!nextBtn || nextBtn.disabled || nextBtn.getAttribute('disabled') !== null) {
      console.log(`✅ Готово. Собрано ${collected.size} треков.`);

      // Формируем содержимое файла
      const lines = [];
      for (const [url, title] of collected.entries()) {
        lines.push(`"${url}" - "${title}"`);
      }
      const fileContent = lines.join('\n');

      // Создаем временный ссылочный элемент для скачивания
      const blob = new Blob([fileContent], {type: 'text/plain'});
      const urlBlob = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = urlBlob;
      a.download = 'list.txt';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(urlBlob);

      break;
    }

    nextBtn.click();
    await delay(1500);
  }
})();
