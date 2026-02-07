"""
MangaTaro scraper
https://mangataro.org

Popular ComicK replacement. Simple requests-based scraper - no protection.
CDN images at bx1.mangapeak.me
"""

import re
from typing import List
from pathlib import Path
from .base import BaseScraper, Chapter, Manga


class MangaTaroScraper(BaseScraper):
    """Scraper for MangaTaro - the ComicK replacement."""
    
    name = "mangataro"
    base_url = "https://mangataro.org"
    cdn_base = "https://bx1.mangapeak.me"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title.
        
        MangaTaro doesn't have a traditional search API, so we:
        1. Try direct URL with slug version of query
        2. Browse the API endpoint and filter client-side
        """
        from bs4 import BeautifulSoup
        
        results = []
        
        # Method 1: Try direct URL construction
        slug = query.lower().replace(" ", "-").replace("'", "").replace(":", "")
        direct_url = f"{self.base_url}/manga/{slug}"
        
        try:
            resp = self.session.get(direct_url, timeout=15)
            if resp.status_code == 200 and "/manga/" in resp.url:
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("title")
                if title_tag and "manga" in title_tag.string.lower():
                    title = title_tag.string.replace(" Manga | Read Online Free at MangaTaro", "").strip()
                    cover = soup.select_one('img[src*="/media/"]')
                    cover_url = cover.get("src") if cover else None
                    results.append(Manga(
                        title=title,
                        url=direct_url,
                        cover_url=cover_url,
                    ))
        except:
            pass
        
        # Method 2: Browse API endpoint and filter
        try:
            api_url = f"{self.base_url}/api/manga?q={query.replace(' ', '+')}"
            resp = self.session.get(api_url, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                query_lower = query.lower()
                for link in soup.select('a[href*="/manga/"]'):
                    href = link.get("href", "")
                    if "/tag/" in href or not href:
                        continue
                    
                    text = link.get_text(strip=True)
                    # Filter by query
                    if text and query_lower in text.lower():
                        manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
                        
                        if manga_url not in [r.url for r in results]:
                            results.append(Manga(
                                title=text,
                                url=manga_url,
                                cover_url=None,
                            ))
        except:
            pass
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga.
        
        MangaTaro has chapters in a dropdown on the reader page.
        We first find a chapter link, then load that page to get the full list.
        """
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        # First, find any chapter link to get to the reader page
        read_link = soup.select_one('a[href*="/read/"]')
        if read_link:
            read_url = read_link.get("href", "")
            if not read_url.startswith("http"):
                read_url = f"{self.base_url}{read_url}"
            
            # Load the reader page to get chapter dropdown
            reader_html = self._get_html(read_url)
            reader_soup = BeautifulSoup(reader_html, "html.parser")
            
            # Find the chapter selector dropdown
            for select in reader_soup.find_all("select"):
                options = select.find_all("option")
                if len(options) > 1:  # Has multiple chapters
                    for option in options:
                        href = option.get("value", "")
                        if "/read/" not in href:
                            continue
                        
                        chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                        chapter_text = option.get_text(strip=True)
                        
                        # Extract chapter number from URL: /read/manga/ch1-8788
                        match = re.search(r'/ch(\d+\.?\d*)-(\d+)', href)
                        if match:
                            chapter_num = match.group(1)
                        else:
                            # Extract from text: "Ch. 1" or "Chapter 1"
                            text_match = re.search(r'(?:ch\.?|chapter)\s*(\d+\.?\d*)', chapter_text, re.I)
                            chapter_num = text_match.group(1) if text_match else "0"
                        
                        if chapter_url not in [c.url for c in chapters]:
                            chapters.append(Chapter(
                                number=chapter_num,
                                title=chapter_text or None,
                                url=chapter_url,
                                date=None,
                            ))
                    
                    if chapters:
                        break  # Found chapters, stop looking
        
        # Fallback: look for chapter links directly on manga page
        if not chapters:
            for link in soup.select('a[href*="/read/"]'):
                href = link.get("href", "")
                if not href or "/read/" not in href:
                    continue
                
                chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                match = re.search(r'/ch(\d+\.?\d*)-(\d+)', href)
                chapter_num = match.group(1) if match else "0"
                
                if chapter_url not in [c.url for c in chapters]:
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=link.get_text(strip=True) or None,
                        url=chapter_url,
                        date=None,
                    ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_html(chapter_url)
        
        # Extract CDN image URLs from the page
        # Pattern: https://bx1.mangapeak.me/storage/chapters/{hash}/{page}.webp
        cdn_pattern = r'https?://[^\s"\'<>\\]+mangapeak\.me/storage/chapters/[a-f0-9]+/\d+\.webp'
        cdn_urls = re.findall(cdn_pattern, html)
        
        if not cdn_urls:
            # Try alternate pattern for mangataro.org URLs
            alt_pattern = r'https?://[^\s"\'<>\\]+/storage/chapters/[a-f0-9]+/\d+\.webp'
            cdn_urls = re.findall(alt_pattern, html)
        
        if not cdn_urls:
            return []
        
        # Get the base URL (chapter hash) from first image
        first_url = cdn_urls[0]
        base_url = first_url.rsplit('/', 1)[0]
        
        # Use CDN domain for better reliability
        if 'mangapeak.me' not in base_url:
            hash_part = base_url.split('/storage/chapters/')[-1]
            base_url = f"{self.cdn_base}/storage/chapters/{hash_part}"
        
        # Enumerate pages by checking which ones exist
        pages = []
        for i in range(1, 200):  # Max 200 pages
            page_url = f"{base_url}/{str(i).zfill(3)}.webp"
            try:
                resp = self.session.head(page_url, timeout=5)
                if resp.status_code == 200:
                    pages.append(page_url)
                else:
                    # Check without zero padding
                    page_url2 = f"{base_url}/{i}.webp"
                    resp2 = self.session.head(page_url2, timeout=5)
                    if resp2.status_code == 200:
                        pages.append(page_url2)
                    else:
                        break  # No more pages
            except:
                break
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
