🇷🇺 **Русский** | [🇺🇸 English](https://github.com/RoganovDA/suno_downloader/blob/main/README.md)

---

<p align="center">
  <a href="https://pay.cloudtips.ru/p/5675a192" target="_blank" rel="noopener">
    <img alt="Поддержать проект"
         src="https://img.shields.io/badge/💛%20Поддержать%20проект-00D1B2?style=for-the-badge&labelColor=222">
  </a>
  <a href="https://pay.cloudtips.ru/p/5675a192" target="_blank" rel="noopener">
    <img alt="CloudTips"
         src="https://img.shields.io/badge/CloudTips-0088CC?style=for-the-badge&labelColor=111">
  </a>
</p>

---

# Массовый загрузчик и парсер песен Suno.com

Набор для **массового скачивания песен и обложек с [suno.com](https://suno.com/create)**:  
браузерный парсер (`devtool.js`) и асинхронный Python-скрипт для загрузки/тэгирования (`suno.py`).

---

## Возможности

- **Парсинг в один клик:** Скрипт для браузера сохраняет все ваши треки в `list.txt`.
- **Массовое скачивание:** Скрипт на Python скачивает и тэггирует mp3 и обложки из списка.
- **Автоматические метаданные:** Обложка, название, автор, копирайт, ссылка — всё в тегах.
- **Логи ошибок:** Отдельный файл с ошибками для отладки.

---

## Как пользоваться

1. **Собрать ссылки:**
   - Откройте [suno.com/create](https://suno.com/create) в браузере.
   - Вставьте содержимое `devtool.js` в консоль разработчика и запустите.
   - Скрипт соберет ссылки на все ваши песни и названия, сохранит файл `list.txt`:
     ```
     "https://suno.com/song/xxxxx" - "Название песни"
     ```

2. **Скачать всё скриптом:**
   - Положите `suno.py` и `list.txt` в одну папку.
   - Установите зависимости:
     ```bash
     pip install -r requirements.txt
     ```
   - Запустите:
     ```bash
     python suno.py
     ```
   - Готовые mp3 с обложками будут в папке `downloads/`.

---

## Состав проекта

- **devtool.js** — парсер ссылок и названий (браузерный скрипт).
- **suno.py** — массовая загрузка .mp3 и обложек, автоматическое заполнение тегов.
- **list.txt** — генерируется devtool.js (список песен).
- **downloads/** — выходная папка с mp3-файлами.
- **tmp/** — временные файлы (автоматически удаляются).
- **errors.log** — журнал ошибок и предупреждений.

---

## Требования

- Python 3.8+
- aiohttp
- tqdm
- mutagen
- Pillow

Пример `requirements.txt`:
aiohttp
tqdm
mutagen
Pillow

---

## Лицензия

MIT, проект не аффилирован с suno.com.

