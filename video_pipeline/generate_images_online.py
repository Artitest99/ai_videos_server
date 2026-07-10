# image_scrape_clip_playwright.py
# Scrapes DuckDuckGo Images using a real headless browser (Playwright),
# ranks with CLIP, saves the best image per prompt.
# Prompts: prompts/{FILE_NAME}.json → [{"filename": "...", "prompt": "..."}, ...]

import os
import json
import time
from io import BytesIO
from typing import List, Tuple, Optional

import requests
from PIL import Image

import torch
import torch.nn.functional as F
import open_clip
from tqdm import tqdm

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

from config import FILE_NAME

# =========================
# CLIP setup
# =========================
device = "cuda" if torch.cuda.is_available() else "cpu"
model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
model = model.to(device).eval()
tokenizer = open_clip.get_tokenizer("ViT-B-32")

# =========================
# HTTP session for image downloads
# =========================
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
})
VALID_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# =========================
# Playwright scraping
# =========================
DDG_IMAGE_SELECTOR = "img.tile--img__img"

def _ddg_search_url(query: str) -> str:
    return f"https://duckduckgo.com/?q={requests.utils.quote(query)}&iax=images&ia=images"

def scrape_ddg_images_with_playwright(query: str, num: int = 24, headless: bool = True) -> List[str]:
    """
    Launches a headless Chromium with Playwright, opens DDG Images,
    scrolls to load a bunch of tiles, and extracts image URLs.
    Returns a list of direct image URLs (best effort).
    """
    urls: List[str] = []
    start = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900},
            java_script_enabled=True,
        )
        page = context.new_page()
        try:
            page.goto(_ddg_search_url(query), wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector(DDG_IMAGE_SELECTOR, timeout=15000)
        except PWTimeoutError:
            print("Timeout loading image grid.")
            context.close(); browser.close()
            return []

        # Scroll to load more tiles (lazy-loaded)
        loaded = 0
        max_scrolls = 12
        for i in range(max_scrolls):
            # Evaluate client-side to collect current srcs
            current_srcs = page.eval_on_selector_all(
                DDG_IMAGE_SELECTOR,
                """els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '')"""
            )
            # Also try to get the high-res URL when present in parent <a> attribute
            parent_links = page.eval_on_selector_all(
                "a.tile--img__img__wrap",
                """els => els.map(e => e.getAttribute('href') || '')"""
            )

            # Merge candidates: prefer <img src>, then parent href (may be redirect)
            candidates = []
            for s in current_srcs:
                if s and s.startswith("http"):
                    candidates.append(s)
            for href in parent_links:
                if href and href.startswith("http"):
                    candidates.append(href)

            # De-dup and filter by ext if possible
            new_urls = []
            seen = set(urls)
            for u in candidates:
                base = u.split("?")[0].lower()
                if any(base.endswith(ext) for ext in VALID_EXTS):
                    if u not in seen:
                        new_urls.append(u)
                        seen.add(u)

            if new_urls:
                urls.extend(new_urls)
                loaded = len(urls)
                # print(f"Loaded {loaded} image URLs…")
                if loaded >= num:
                    break

            # Scroll down to trigger more loads
            page.evaluate("window.scrollBy(0, window.innerHeight * 0.9);")
            page.wait_for_timeout(600 + i * 80)

        context.close()
        browser.close()

    # Limit to requested number
    urls = urls[:num]

    # As a fallback: if too few direct URLs, also accept data-src/thumbnail without extension
    if len(urls) < num:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1400, "height": 900},
            )
            page = context.new_page()
            try:
                page.goto(_ddg_search_url(query), wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector(DDG_IMAGE_SELECTOR, timeout=15000)
                # take any URL-like src if direct extensions were scarce
                fallback_srcs = page.eval_on_selector_all(
                    DDG_IMAGE_SELECTOR,
                    """els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src') || '')"""
                )
                for u in fallback_srcs:
                    if u and u.startswith("http") and u not in urls:
                        urls.append(u)
                        if len(urls) >= num:
                            break
            except PWTimeoutError:
                pass
            finally:
                context.close()
                browser.close()

    # Final trim
    return urls[:num]

# =========================
# Download image
# =========================
def download_image(url: str) -> Optional[Image.Image]:
    try:
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        return img
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return None

# =========================
# CLIP ranking
# =========================
def rank_images(prompt: str, image_urls: List[str]) -> List[Tuple[str, float]]:
    tokens = tokenizer([prompt]).to(device)
    with torch.no_grad():
        text_feats = model.encode_text(tokens)
        text_feats = F.normalize(text_feats, dim=-1)

    ranked: List[Tuple[str, float]] = []
    for url in tqdm(image_urls, desc="Ranking images"):
        img = download_image(url)
        if img is None:
            continue
        try:
            img_tensor = preprocess(img).unsqueeze(0).to(device)
            with torch.no_grad():
                image_feats = model.encode_image(img_tensor)
                image_feats = F.normalize(image_feats, dim=-1)
                sim = (text_feats @ image_feats.T).squeeze().item()
            ranked.append((url, sim))
        except Exception as e:
            print(f"CLIP error for {url}: {e}")
            continue

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked

# =========================
# Helpers & main
# =========================
def load_prompts(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    PROMPTS_PATH = f"prompts/{FILE_NAME}.json"
    OUTPUT_DIR = f"assets/media/{FILE_NAME}/web"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    prompts = load_prompts(PROMPTS_PATH)
    if not isinstance(prompts, list):
        print(f"Prompt file must be a list of objects. Got {type(prompts)}")
        return

    for i, entry in enumerate(prompts):
        name = entry.get("filename") or entry.get("name") or f"img{i+1}"
        prompt = entry.get("prompt") or entry.get("text")
        if not prompt:
            print(f"Skipping entry {i}: no 'prompt' found.")
            continue

        print(f"\n=== [{i+1}/{len(prompts)}] {name} ===")
        print(f"Query: {prompt}")
        output_path = os.path.join(OUTPUT_DIR, f"{name}.png")

        # 1) Scrape images with a real browser
        urls = scrape_ddg_images_with_playwright(prompt, num=28, headless=True)
        if not urls:
            print("No images found via Playwright scraping. Continuing.")
            continue

        # 2) Rank with CLIP
        print("🤖 Ranking images using CLIP…")
        ranked = rank_images(prompt, urls)
        if not ranked:
            print("No valid images to rank. Continuing.")
            continue

        # 3) Download and save best
        best_url, score = ranked[0]
        print(f"✅ Best Match:\n{best_url}\nSimilarity: {score:.4f}")

        img = download_image(best_url)
        if img is None:
            print("Failed to download best image. Continuing.")
            continue

        try:
            img.save(output_path)
            print(f"📸 Saved: {output_path}")
        except Exception as e:
            print(f"Error saving to {output_path}: {e}")

if __name__ == "__main__":
    main()
