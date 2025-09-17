#!/usr/bin/env python3
import os
import re
import csv
import json
import glob
import aiohttp
import asyncio
import shutil
import uuid
import random
from typing import List, Tuple, Optional, Dict
from contextlib import asynccontextmanager

from mutagen.id3 import ID3, APIC, COMM, TPE1, TPE2, TCOP, WXXX, TIT2, ID3NoHeaderError
from tqdm import tqdm
from PIL import Image

# ===================== CONFIG ===================== #
DOWNLOAD_DIR      = 'downloads'
TMP_DIR           = 'tmp'
AUTHOR            = "RoganovDA"
PUBLISHER         = "RoganovDA"
AUTHOR_URL        = "https://t.me/slow_rda"
COPYRIGHT         = "Copyright © RoganovDA"
CONCURRENT_TASKS  = 5
RETRIES           = 3
TIMEOUT_SECS      = 60
LOG_FILE          = 'errors.log'
USER_AGENT        = "Mozilla/5.0 (compatible; SunoGrabber/1.1; +https://example.local)"
# ================================================== #

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
            rgb = im.convert('RGB')
            rgb.save(out_jpg, format="JPEG", quality=92, optimize=True)
        return out_jpg
    except Exception as e:
        log(f"[WARN] JPEG convert failed for {image_file}: {e}")
        return image_file

def tag_mp3(mp3_file: str, title: str, image_file: Optional[str], source_url: Optional[str]):
    try:
        try:
            audio = ID3(mp3_file)
        except ID3NoHeaderError:
            audio = ID3()

        audio.delall('APIC')
        if image_file and os.path.exists(image_file) and os.path.getsize(image_file) > 1024:
            jpeg_image = ensure_jpeg(image_file)
            with open(jpeg_image, 'rb') as img:
                audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img.read()))
        else:
            log(f"[WARN] No cover present for {mp3_file}")

        audio.delall('TIT2')
        audio.add(TIT2(encoding=3, text=title))
        audio['COMM'] = COMM(encoding=3, lang='eng', desc='desc', text=title)
        audio['TPE1'] = TPE1(encoding=3, text=AUTHOR)
        audio['TPE2'] = TPE2(encoding=3, text=PUBLISHER)
        audio['TCOP'] = TCOP(encoding=3, text=COPYRIGHT)

        audio.delall('WXXX')
        audio.add(WXXX(encoding=3, desc='Author URL', url=AUTHOR_URL))
        if source_url:
            audio.add(WXXX(encoding=3, desc='Source URL (suno)', url=source_url))

        audio.save(mp3_file, v2_version=3)
        return True
    except Exception as e:
        log(f"[ERROR] Failed to tag {mp3_file}: {e}")
        return False

# === Жёстко зашитые URL-паттерны под твою схему: mp3 на cdn1, обложка на cdn2 ===
def audio_url(song_id: str) -> str:
    return f"https://cdn1.suno.ai/{song_id}.mp3"

def cover_url(song_id: str) -> str:
    return f"https://cdn2.suno.ai/image_{song_id}.jpeg"

@asynccontextmanager
async def fetch_ctx(session: aiohttp.ClientSession, url: str):
    async with session.get(url, timeout=TIMEOUT_SECS) as resp:
        resp.raise_for_status()
        yield resp

async def download_to(session: aiohttp.ClientSession, url: str, filename: str) -> bool:
    try:
        async with fetch_ctx(session, url) as resp:
            server_size = int(resp.headers.get('content-length', 0)) or None
            with open(filename, 'wb') as f, tqdm(total=server_size, desc=os.path.basename(filename),
                                                 unit='B', unit_scale=True, leave=False) as pbar:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    f.write(chunk)
                    if server_size:
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
        except:  # noqa
            pass
        return False

async def download_with_retries(session: aiohttp.ClientSession, url: str, filename: str) -> bool:
    for attempt in range(1, RETRIES + 1):
        ok = await download_to(session, url, filename)
        if ok:
            return True
        await asyncio.sleep(1.0 * attempt)
    return False

# ===== парсинг входных форматов =====
def parse_legacy_txt_line(line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
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
    head_stripped = head.lstrip("\ufeff").strip()
    if head_stripped.startswith('['):
        return 'json'
    if '\t' in head and ',' not in head:
        return 'tsv'
    if head_stripped.startswith('"https://suno.com/song/'):
        return 'txt'
    return 'csv'

def load_input(path: str) -> List[Dict[str, str]]:
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
                items.append({'id': song_id, 'url': url or f'https://suno.com/song/{song_id}', 'title': title or 'Untitled'})

    elif fmt in ('csv', 'tsv'):
        delim = ',' if fmt == 'csv' else '\t'
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f, delimiter=delim)
            rows = list(reader)
        header = [c.strip().lower() for c in rows[0]] if rows else []
        start_idx = 1 if header and {'id','url','title'}.issubset(set(header)) else 0
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
                items.append({'id': song_id, 'url': url or f'https://suno.com/song/{song_id}', 'title': title or 'Untitled'})

    else:  # legacy txt
        with open(path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                song_id, url, title = parse_legacy_txt_line(line)
                if song_id:
                    items.append({'id': song_id, 'url': url or f'https://suno.com/song/{song_id}', 'title': title or 'Untitled'})

    return items

async def process_item(session: aiohttp.ClientSession, sem: asyncio.Semaphore, idx: int, item: Dict[str, str]) -> bool:
    song_id = item['id']
    url = item.get('url') or f'https://suno.com/song/{song_id}'
    title = item.get('title') or 'Untitled'
    filename_base = clean_filename(title)

    uid = str(uuid.uuid4())
    tmp_folder = os.path.join(TMP_DIR, uid)
    os.makedirs(tmp_folder, exist_ok=True)
    mp3_tmp = os.path.join(tmp_folder, "audio.mp3")
    img_tmp = os.path.join(tmp_folder, "cover.jpeg")

    try:
        async with sem:
            # строго твои эндпоинты
            audio_ok = await download_with_retries(session, audio_url(song_id), mp3_tmp)
            if not audio_ok:
                log(f"[{idx}] [FAIL] audio not found for {song_id} ({title})")
                return False

            cover_ok = await download_with_retries(session, cover_url(song_id), img_tmp)
            if not cover_ok:
                img_tmp_path = None
                log(f"[{idx}] [WARN] cover not found for {song_id} ({title})")
            else:
                img_tmp_path = img_tmp

            # теги + перенос
            tag_mp3(mp3_tmp, title, img_tmp_path, source_url=url)
            final_mp3 = get_free_filename(filename_base, ".mp3")
            shutil.move(mp3_tmp, final_mp3)
            log(f"[OK] {title} -> {final_mp3}")
            return True
    except Exception as e:
        log(f"[{idx}] [ERROR] {song_id} ({title}): {e}")
        return False
    finally:
        shutil.rmtree(tmp_folder, ignore_errors=True)

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
    Выбираем случайный входной файл из текущей папки с приоритетом JSON.
    Группы в порядке убывания приоритета:
    1) *.json
    2) *.csv
    3) *.tsv
    4) list.txt
    """
    cwd = os.getcwd()
    groups = [
        glob.glob(os.path.join(cwd, "*.json")),
        glob.glob(os.path.join(cwd, "*.csv")),
        glob.glob(os.path.join(cwd, "*.tsv")),
        [os.path.join(cwd, "list.txt")] if os.path.exists("list.txt") else []
    ]
    for files in groups:
        files = [f for f in files if os.path.isfile(f)]
        if files:
            return random.choice(files)
    return None

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

    sem = asyncio.Semaphore(CONCURRENT_TASKS)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=TIMEOUT_SECS, sock_read=TIMEOUT_SECS)
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [process_item(session, sem, i, item) for i, item in enumerate(items, 1)]
        results = await asyncio.gather(*tasks)

    clean_tmp_dir()
    total = len(items)
    ok = sum(1 for r in results if r)
    print(f"Done. Success: {ok} / {total}. См. {LOG_FILE} для деталей.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Suno downloader (cdn1 mp3 / cdn2 jpeg) + auto input pick")
    parser.add_argument('--input', '-i', help='Путь к входному файлу (json/csv/tsv/txt). Если не указан — случайный файл в текущей папке с приоритетом *.json')
    args = parser.parse_args()
    asyncio.run(main(args.input))
