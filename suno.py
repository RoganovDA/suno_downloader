import os
import re
import aiohttp
import asyncio
import shutil
import uuid
from mutagen.id3 import ID3, APIC, COMM, TPE1, TPE2, TCOP, WXXX, TIT2
from tqdm import tqdm
from PIL import Image

DOWNLOAD_DIR = 'downloads'
TMP_DIR = 'tmp'
AUTHOR = "RoganovDA"
PUBLISHER = "RoganovDA"
AUTHOR_URL = "https://t.me/slow_rda"
COPYRIGHT = "Copyright © RoganovDA"
CONCURRENT_TASKS = 5
LOG_FILE = 'errors.log'

def clean_filename(text):
    name = re.sub(r'[<>:"/\\|?*\n\r]', '_', text)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def get_free_filename(base, ext):
    for v in range(1, 1000):
        suffix = "" if v == 1 else f" v{v}"
        candidate = os.path.join(DOWNLOAD_DIR, f"{base}{suffix}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise Exception(f"Too many duplicate files for {base}{ext}")

def log(msg):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg.strip() + "\n")

def ensure_jpeg(image_file):
    out_jpg = image_file.rsplit('.', 1)[0] + ".jpg"
    try:
        with Image.open(image_file) as im:
            rgb = im.convert('RGB')
            rgb.save(out_jpg, format="JPEG", quality=92)
        return out_jpg
    except Exception as e:
        log(f"[WARN] JPEG convert failed: {e}")
        return image_file

def tag_mp3(mp3_file, title, image_file, author=AUTHOR):
    try:
        audio = ID3(mp3_file)
        audio.delall('APIC')
        jpeg_image = ensure_jpeg(image_file)
        cover_applied = False
        if os.path.exists(jpeg_image) and os.path.getsize(jpeg_image) > 1024:
            with open(jpeg_image, 'rb') as img:
                audio.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,
                    desc='Cover',
                    data=img.read()
                ))
            cover_applied = True
        else:
            log(f"[FAIL] No cover: {jpeg_image}")
        audio.add(TIT2(encoding=3, text=title))
        audio['COMM'] = COMM(encoding=3, lang='eng', desc='desc', text=title)
        audio['TPE1'] = TPE1(encoding=3, text=author)
        audio['TPE2'] = TPE2(encoding=3, text=PUBLISHER)
        audio['TCOP'] = TCOP(encoding=3, text=COPYRIGHT)
        audio['WXXX'] = WXXX(encoding=3, desc='Author URL', url=AUTHOR_URL)
        audio.save(mp3_file, v2_version=3)
        if jpeg_image != image_file and os.path.exists(jpeg_image):
            os.remove(jpeg_image)
        return cover_applied
    except Exception as e:
        log(f"[ERROR] Failed to tag {mp3_file}: {e}")
        return False

async def download(session, url, filename):
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            server_size = int(resp.headers.get('content-length', 0))
            with open(filename, 'wb') as f:
                with tqdm(total=server_size or None, desc=os.path.basename(filename), unit='B', unit_scale=True, leave=False) as pbar:
                    async for chunk in resp.content.iter_chunked(1024):
                        f.write(chunk)
                        pbar.update(len(chunk))
        if os.path.getsize(filename) < 1024:
            log(f"[WARN] File {filename} too small!")
            return False
        return True
    except Exception as e:
        log(f"[ERROR] Download failed for {url}: {e}")
        return False

def parse_line(line):
    match = re.match(r'"(https://suno\.com/song/[a-z0-9\-]+)"\s*-\s*"(.*)"', line.strip())
    if not match:
        return None, None
    return match.groups()

async def process_line(session, semaphore, i, line):
    url, title = parse_line(line)
    if not url or not title:
        log(f"[{i}] [SKIP] Invalid line: {line.strip()}")
        return False

    song_id = url.rstrip('/').split('/')[-1]
    filename_base = clean_filename(title)

    # Временная уникальная папка
    uid = str(uuid.uuid4())
    tmp_folder = os.path.join(TMP_DIR, uid)
    os.makedirs(tmp_folder, exist_ok=True)

    mp3_tmp = os.path.join(tmp_folder, "audio.mp3")
    img_tmp = os.path.join(tmp_folder, "cover.jpeg")

    mp3_url = f"https://cdn1.suno.ai/{song_id}.mp3"
    img_url = f"https://cdn2.suno.ai/image_{song_id}.jpeg"

    try:
        async with semaphore:
            res_mp3 = await download(session, mp3_url, mp3_tmp)
            if not res_mp3:
                log(f"[{i}] [FAIL] Audio download failed: {title}")
                shutil.rmtree(tmp_folder, ignore_errors=True)
                return False

            res_img = await download(session, img_url, img_tmp)
            if not res_img:
                log(f"[{i}] [WARN] Cover download failed: {title}")

            tag_mp3(mp3_tmp, title, img_tmp)
            final_mp3 = get_free_filename(filename_base, ".mp3")
            shutil.move(mp3_tmp, final_mp3)
        return True
    finally:
        # Гарантированно удаляем свою временную папку
        shutil.rmtree(tmp_folder, ignore_errors=True)

def clean_tmp_dir():
    if os.path.exists(TMP_DIR):
        for entry in os.listdir(TMP_DIR):
            full_path = os.path.join(TMP_DIR, entry)
            try:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path, ignore_errors=True)
                elif os.path.isfile(full_path):
                    os.remove(full_path)
            except Exception as e:
                log(f"[ERROR] Can't remove {full_path}: {e}")

async def main():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    if not os.path.exists(TMP_DIR):
        os.makedirs(TMP_DIR)
    # Очищаем tmp полностью перед стартом
    clean_tmp_dir()
    # Чистим лог в начале работы
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")
    with open('list.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    semaphore = asyncio.Semaphore(CONCURRENT_TASKS)
    async with aiohttp.ClientSession() as session:
        tasks = [process_line(session, semaphore, i, line) for i, line in enumerate(lines, 1)]
        results = await asyncio.gather(*tasks)
    # После завершения ещё раз чистим tmp (на всякий случай)
    clean_tmp_dir()
    total = len(lines)
    ok = sum(bool(r) for r in results)
    print(f"Done. Success: {ok} / {total} (см. {LOG_FILE} для ошибок и отладочных сообщений)")

if __name__ == "__main__":
    asyncio.run(main())
