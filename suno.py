#!/usr/bin/env python3
import os
import re
import csv
import json
import glob
import uuid
import random
import shutil
import asyncio
from typing import List, Tuple, Optional, Dict

import aiohttp
from contextlib import asynccontextmanager
from tqdm import tqdm
from PIL import Image
from mutagen.id3 import (
    ID3, APIC, COMM, TPE1, TPE2, TCOP, WXXX, TIT2, ID3NoHeaderError
)

# ===================== CONFIG ===================== #
DOWNLOAD_DIR       = 'downloads'
TMP_DIR            = 'tmp'
AUTHOR             = "RoganovDA"
PUBLISHER          = "RoganovDA"
AUTHOR_URL         = "https://t.me/slow_rda"
COPYRIGHT          = "Copyright © RoganovDA"

CONCURRENT_AUDIO   = 5   # параллельно аудио
CONCURRENT_COVER   = 1   # обложки последовательно (увеличь до 2 при желании)
RETRIES            = 5
TIMEOUT_SECS       = 90
LOG_FILE           = 'errors.log'

BASE_ORIGIN        = "https://suno.com"
USER_AGENT         = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
# ================================================== #


# ------------------ utility & logging ------------------ #
def log(msg: str):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def clean_filename(text: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\n\r]', '_', text)
    name = re.sub(r'\s+', ' ', name).strip()
    return name or "Untitled"


def get_free_filename(base: str, ext: str) -> str:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    for v in range(1, 10000):
        suffix = "" if v == 1 else f" v{v}"
        candidate = os.path.join(DOWNLOAD_DIR, f"{base}{suffix}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"Too many duplicate files for {base}{ext}")


def ensure_jpeg(image_file: str) -> str:
    if not os.path.exists(image_file):
        return image_file
    root, _ = os.path.splitext(image_file)
    out_jpg = root + ".jpg"
    try:
        with Image.open(image_file) as im:
            im.convert('RGB').save(out_jpg, format="JPEG", quality=92, optimize=True)
        return out_jpg
    except Exception as e:
        log(f"[WARN] JPEG convert failed for {image_file}: {e}")
        return image_file


def write_apic(mp3_file: str, image_file: str):
    """Добавить/обновить APIC в уже сохранённый mp3."""
    try:
        try:
            audio = ID3(mp3_file)
        except ID3NoHeaderError:
            audio = ID3()
        audio.delall('APIC')
        jpeg_image = ensure_jpeg(image_file)
        with open(jpeg_image, 'rb') as img:
            audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img.read()))
        audio.save(mp3_file, v2_version=3)
        return True
    except Exception as e:
        log(f"[ERROR] APIC update failed for {mp3_file}: {e}")
        return False


def tag_mp3_full(mp3_file: str, title: str, image_file: Optional[str], source_url: Optional[str]):
    """Полная простановка тегов при первичном сохранении."""
    try:
        try:
            audio = ID3(mp3_file)
        except ID3NoHeaderError:
            audio = ID3()

        # Cover (если есть)
        audio.delall('APIC')
        if image_file and os.path.exists(image_file) and os.path.getsize(image_file) > 1024:
            jpeg_image = ensure_jpeg(image_file)
            with open(jpeg_image, 'rb') as img:
                audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img.read()))
        else:
            log(f"[WARN] No cover for {os.path.basename(mp3_file)}")

        # Basic tags
        audio.delall('TIT2')
        audio.add(TIT2(encoding=3, text=title))
        audio['COMM'] = COMM(encoding=3, lang='eng', desc='desc', text=title)
        audio['TPE1'] = TPE1(encoding=3, text=AUTHOR)
        audio['TPE2'] = TPE2(encoding=3, text=PUBLISHER)
        audio['TCOP'] = TCOP(encoding=3, text=COPYRIGHT)

        # URLs
        audio.delall('WXXX')
        audio.add(WXXX(encoding=3, desc='Author URL', url=AUTHOR_URL))
        if source_url:
            audio.add(WXXX(encoding=3, desc='Source URL (suno)', url=source_url))

        audio.save(mp3_file, v2_version=3)
        return True
    except Exception as e:
        log(f"[ERROR] Failed to tag {mp3_file}: {e}")
        return False


# ------------------ fixed CDN endpoints ------------------ #
def audio_url(song_id: str) -> str:
    # MP3 строго на cdn1
    return f"https://cdn1.suno.ai/{song_id}.mp3"


def cover_url(song_id: str) -> str:
    # JPEG строго на cdn2
    return f"https://cdn2.suno.ai/image_{song_id}.jpeg"


# ------------------ HTTP helpers ------------------ #
def exp_backoff(attempt: int) -> float:
    # 0.5, 1, 2, 4, 6 сек (с легким джиттером)
    base = min(0.5 * (2 ** (attempt - 1)), 6.0)
    jitter = random.uniform(0, 0.3)
    return base + jitter


@asynccontextmanager
async def fetch_ctx(session: aiohttp.ClientSession, url: str,
                    headers: Optional[Dict[str, str]] = None):
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    async with session.get(url, headers=hdrs, timeout=TIMEOUT_SECS) as resp:
        resp.raise_for_status()
        yield resp


async def download_to(session: aiohttp.ClientSession, url: str, filename: str,
                      headers: Optional[Dict[str, str]] = None) -> bool:
    try:
        async with fetch_ctx(session, url, headers) as resp:
            total = int(resp.headers.get("content-length", 0)) or None
            with open(filename, "wb") as f, tqdm(
                total=total, desc=os.path.basename(filename),
                unit="B", unit_scale=True, leave=False
            ) as pbar:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    f.write(chunk)
                    if total:
                        pbar.update(len(chunk))
        if os.path.getsize(filename) < 1024:
            log(f"[WARN] tiny file from {url}")
            return False
        return True
    except Exception as e:
        log(f"[ERROR] download failed: {url} -> {e}")
        try:
            if os.path.exists(filename) and os.path.getsize(filename) == 0:
                os.remove(filename)
        except Exception:
            pass
        return False


async def download_audio(session: aiohttp.ClientSession, url: str, filename: str) -> bool:
    # аудио обычно стабильно, но добавим ретраи
    for attempt in range(1, RETRIES + 1):
        ok = await download_to(
            session, url, filename,
            headers={"Referer": BASE_ORIGIN, "User-Agent": USER_AGENT}
        )
        if ok:
            return True
        await asyncio.sleep(exp_backoff(attempt))
    return False


async def download_cover_safely(session: aiohttp.ClientSession, song_id: str,
                                song_url: str, out_path: str,
                                counters: Dict[str, int]) -> bool:
    """
    Качаем обложку с cdn2, пробуя разные наборы заголовков последовательно.
    Плюс экспоненциальный бэкофф и счётчики ошибок.
    """
    url = cover_url(song_id)
    header_sets = [
        # 1) Широкий Accept (часто достаточно)
        {
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
        # 2) С реферером страницы трека
        {
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": song_url,
        },
        # 3) С реферером + origin
        {
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": song_url,
            "Origin": BASE_ORIGIN,
        },
        # 4) Минимальные заголовки
        {},
    ]

    for headers in header_sets:
        for attempt in range(1, RETRIES + 1):
            ok = await download_to(session, url, out_path, headers=headers)
            if ok:
                return True
            await asyncio.sleep(exp_backoff(attempt))
            counters['cover_retries'] += 1
    return False


# ------------------ input parsing ------------------ #
def parse_legacy_txt_line(line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    # "https://suno.com/song/<uuid>" - "Title"
    m = re.match(r'"\s*(https://suno\.com/song/[a-z0-9\-]+)\s*"\s*-\s*"(.*)"\s*$', line.strip(), re.IGNORECASE)
    if not m:
        return None, None, None
    url = m.group(1)
    title = m.group(2)
    song_id = url.rstrip('/').split('/')[-1]
    return song_id, url, title


def sniff_format_by_name_or_content(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.json', '.csv', '.tsv', '.txt'):
        return ext[1:]
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        head = f.read(2048)
    head = head.lstrip("\ufeff").strip()
    if head.startswith('['):
        return 'json'
    if '\t' in head and ',' not in head:
        return 'tsv'
    if head.startswith('"https://suno.com/song/'):
        return 'txt'
    return 'csv'


def load_input(path: str) -> List[Dict[str, str]]:
    """
    Возвращает список словарей {id, url, title}
    Поддерживает json/csv/tsv/txt (legacy).
    """
    fmt = sniff_format_by_name_or_content(path)
    items: List[Dict[str, str]] = []

    if fmt == 'json':
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        for row in data:
            song_id = (row.get('id') or '').strip()
            url = (row.get('url') or '').strip()
            title = (row.get('title') or '').strip()
            if not song_id and url:
                song_id = url.rstrip('/').split('/')[-1]
            if song_id:
                items.append({
                    'id': song_id,
                    'url': url or f'{BASE_ORIGIN}/song/{song_id}',
                    'title': title or 'Untitled'
                })

    elif fmt in ('csv', 'tsv'):
        delim = ',' if fmt == 'csv' else '\t'
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f, delimiter=delim)
            rows = list(reader)
        header = [c.strip().lower() for c in rows[0]] if rows else []
        start_idx = 1 if header and {'id', 'url', 'title'}.issubset(set(header)) else 0
        for r in rows[start_idx:]:
            if not r:
                continue
            id_col, url_col, title_col = (r + ["", "", ""])[:3]
            song_id = (id_col or "").strip()
            url = (url_col or "").strip()
            title = (title_col or "").strip()
            if not song_id and url:
                song_id = url.rstrip('/').split('/')[-1]
            if song_id:
                items.append({
                    'id': song_id,
                    'url': url or f'{BASE_ORIGIN}/song/{song_id}',
                    'title': title or 'Untitled'
                })

    else:  # txt legacy
        with open(path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                song_id, url, title = parse_legacy_txt_line(line)
                if song_id:
                    items.append({
                        'id': song_id,
                        'url': url or f'{BASE_ORIGIN}/song/{song_id}',
                        'title': title or 'Untitled'
                    })

    return items


# ------------------ worker ------------------ #
async def process_item(session: aiohttp.ClientSession,
                       audio_sem: asyncio.Semaphore,
                       cover_sem: asyncio.Semaphore,
                       idx: int,
                       item: Dict[str, str],
                       counters: Dict[str, int]) -> Dict[str, Optional[str]]:
    """
    Возвращает словарь с итогами по треку:
    {
      'id', 'title', 'url', 'mp3_path', 'cover_ok' (bool)
    }
    """
    song_id = item['id']
    song_url = item.get('url') or f'{BASE_ORIGIN}/song/{song_id}'
    title = item.get('title') or 'Untitled'
    filename_base = clean_filename(title)

    uid = str(uuid.uuid4())
    tmp_folder = os.path.join(TMP_DIR, uid)
    os.makedirs(tmp_folder, exist_ok=True)
    mp3_tmp = os.path.join(tmp_folder, "audio.mp3")
    img_tmp = os.path.join(tmp_folder, "cover.jpeg")

    final_mp3 = None
    cover_ok = False

    try:
        # 1) MP3 — параллельно
        async with audio_sem:
            ok_audio = await download_audio(session, audio_url(song_id), mp3_tmp)
        if not ok_audio:
            log(f"[{idx}] [FAIL] audio not found for {song_id} ({title})")
            counters['audio_fail'] += 1
            return {'id': song_id, 'title': title, 'url': song_url, 'mp3_path': None, 'cover_ok': False}

        # 2) Обложка — ограниченная параллель
        async with cover_sem:
            cover_ok = await download_cover_safely(session, song_id, song_url, img_tmp, counters)

        # 3) Теги и перенос
        tag_mp3_full(mp3_tmp, title, img_tmp if cover_ok else None, source_url=song_url)
        final_mp3 = get_free_filename(filename_base, ".mp3")
        shutil.move(mp3_tmp, final_mp3)
        log(f"[OK] {title} -> {final_mp3}")

        counters['audio_ok'] += 1
        if cover_ok:
            counters['cover_ok'] += 1
        else:
            counters['cover_fail'] += 1

        return {'id': song_id, 'title': title, 'url': song_url, 'mp3_path': final_mp3, 'cover_ok': cover_ok}
    except Exception as e:
        log(f"[{idx}] [ERROR] {song_id} ({title}): {e}")
        counters['audio_fail'] += 1
        return {'id': song_id, 'title': title, 'url': song_url, 'mp3_path': None, 'cover_ok': False}
    finally:
        shutil.rmtree(tmp_folder, ignore_errors=True)


# ------------------ housekeeping ------------------ #
def clean_tmp_dir():
    if os.path.exists(TMP_DIR):
        for entry in os.listdir(TMP_DIR):
            full = os.path.join(TMP_DIR, entry)
            try:
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                elif os.path.isfile(full):
                    os.remove(full)
            except Exception as e:
                log(f"[ERROR] can't remove {full}: {e}")


def pick_default_input() -> Optional[str]:
    """
    Выбираем случайный входной файл из текущей папки (приоритет: *.json -> *.csv -> *.tsv -> list.txt)
    """
    groups = [
        glob.glob("*.json"),
        glob.glob("*.csv"),
        glob.glob("*.tsv"),
        ["list.txt"] if os.path.exists("list.txt") else []
    ]
    for files in groups:
        files = [f for f in files if os.path.isfile(f)]
        if files:
            return random.choice(files)
    return None


# ------------------ main ------------------ #
async def main(input_path: Optional[str] = None):
    if input_path is None:
        input_path = pick_default_input()
    if not input_path or not os.path.exists(input_path):
        raise SystemExit("Не найден входной файл. Положи рядом *.json/ *.csv/ *.tsv/ list.txt или укажи --input путь.")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    clean_tmp_dir()
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    items = load_input(input_path)
    if not items:
        raise SystemExit(f"Нет валидных записей в {input_path} (нужны поля id/url/title).")

    print(f"Input file: {os.path.basename(input_path)} ({len(items)} записей)")

    # Ограничим соединения на хост (уменьшает шанс 403/50x от CDN)
    connector = aiohttp.TCPConnector(limit_per_host=2, limit=0, ttl_dns_cache=300)

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=TIMEOUT_SECS, sock_read=TIMEOUT_SECS)
    default_headers = {"User-Agent": USER_AGENT, "Referer": BASE_ORIGIN}

    counters = {'audio_ok': 0, 'audio_fail': 0, 'cover_ok': 0, 'cover_fail': 0, 'cover_retries': 0}

    audio_sem = asyncio.Semaphore(CONCURRENT_AUDIO)
    cover_sem = asyncio.Semaphore(CONCURRENT_COVER)

    async with aiohttp.ClientSession(timeout=timeout, headers=default_headers, connector=connector) as session:
        tasks = [
            process_item(session, audio_sem, cover_sem, i, item, counters)
            for i, item in enumerate(items, 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    # Финальный последовательный добор обложек: где не удалось — попробуем ещё раз и обновим APIC
    missing = [r for r in results if r.get('mp3_path') and not r.get('cover_ok')]
    if missing:
        print(f"Final cover pass: trying to fetch covers for {len(missing)} items sequentially…")
        async with aiohttp.ClientSession(timeout=timeout, headers=default_headers, connector=connector) as session:
            for r in missing:
                song_id = r['id']; song_url = r['url']; mp3_path = r['mp3_path']
                tmp_img = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}.jpeg")
                ok = await download_cover_safely(session, song_id, song_url, tmp_img, counters)
                if ok and os.path.exists(tmp_img):
                    if write_apic(mp3_path, tmp_img):
                        counters['cover_ok'] += 1
                        counters['cover_fail'] = max(0, counters['cover_fail'] - 1)
                    os.remove(tmp_img)
                await asyncio.sleep(0.2)  # микропаузa между обложками

    clean_tmp_dir()

    total = len(items)
    print(f"\nDone. Audio OK: {counters['audio_ok']}/{total}, "
          f"Covers OK: {counters['cover_ok']}/{total}, "
          f"Covers retries: {counters['cover_retries']}, "
          f"Audio fail: {counters['audio_fail']}, Cover fail: {counters['cover_fail']}.")
    print(f"См. {LOG_FILE} для деталей.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Suno downloader (cdn1 mp3 + robust cdn2 cover) with 2-phase cover tagging")
    parser.add_argument('--input', '-i', help='Входной файл (json/csv/tsv/txt). Если не указан — случайный файл в текущей папке (приоритет JSON).')
    args = parser.parse_args()
    asyncio.run(main(args.input))
