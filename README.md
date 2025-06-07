# Suno.com Bulk Song Downloader & Parser

A toolkit for **bulk downloading songs and covers from [suno.com](https://suno.com/create)** using a browser-side parser (`devtool.js`) and a Python async downloader/tagger (`suno.py`).

---

## Features

- **Easy scraping:** Use a browser script to save all your Suno song links and titles.
- **Batch download:** Download and tag many tracks at once from a simple text list.
- **Auto-metadata:** Songs get cover art, title, author, copyright, and link.
- **Handles errors & retries:** Detailed logs if something goes wrong.

---

## How it works

1. **Collect links:**
   - Open [suno.com/create](https://suno.com/create) in your browser.
   - Run `devtool.js` in the browser console.
   - It collects all your songs and saves a `list.txt` file with lines like:
     ```
     "https://suno.com/song/xxxxx" - "Song Title"
     ```

2. **Bulk download:**
   - Place `suno.py` and `list.txt` in the same directory.
   - Install dependencies:
     ```bash
     pip install -r requirements.txt
     ```
   - Run the script:
     ```bash
     python suno.py
     ```
   - Downloads will appear in the `downloads/` folder, covers embedded.

---

## Files

- **devtool.js** – Browser script to collect song URLs & titles from Suno.
- **suno.py** – Python downloader: grabs .mp3 and cover for each song, tags metadata.
- **list.txt** – The generated song list from devtool.js.
- **downloads/** – Output directory for .mp3 files.
- **tmp/** – Temporary files (auto cleaned).
- **errors.log** – Log file with download/tagging errors.

---

## Requirements

- Python 3.8+
- aiohttp
- tqdm
- mutagen
- Pillow

Example for `requirements.txt`:
aiohttp
tqdm
mutagen
Pillow


---

## License

MIT, no affiliation with suno.com.

