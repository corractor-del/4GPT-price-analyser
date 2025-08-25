
from __future__ import annotations
import os, io, time, re, threading, random, logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple

import requests
from http.cookiejar import MozillaCookieJar
import pandas as pd

log = logging.getLogger(__name__)

# ------------------------- Rate limiter -------------------------
class TokenBucket:
    def __init__(self, rate_per_minute: int, burst: int = 5):
        self.capacity = max(1, burst)
        self.tokens = self.capacity
        self.rate = max(1, rate_per_minute) / 60.0
        self.lock = threading.Lock()
        self.last = time.perf_counter()

    def acquire(self, stop_event: Optional[threading.Event] = None):
        while True:
            if stop_event is not None and stop_event.is_set():
                raise StopIteration
            with self.lock:
                now = time.perf_counter()
                delta = now - self.last
                self.last = now
                self.tokens = min(self.capacity, self.tokens + delta * self.rate)
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                need = (1 - self.tokens) / self.rate
            # Sleep in small chunks to be stop-able
            t = 0.0
            while t < max(0.05, need):
                if stop_event is not None and stop_event.is_set():
                    raise StopIteration
                sl = min(0.1, max(0.05, need) - t)
                time.sleep(sl)
                t += sl

# ------------------------- HTTP client -------------------------
@dataclass
class ClientConfig:
    base_url: str = 'https://www.avito.ru/'
    timeout: int = 25
    rate_per_min: int = 12   # adjust conservatively
    burst: int = 3
    user_agent: str = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0 Safari/537.36'
    )

class AvitoClient:
    def __init__(self, cookies_path: Optional[str], cfg: ClientConfig):
        self.s = requests.Session()
        self.s.headers.update({'User-Agent': cfg.user_agent, 'Accept-Language': 'ru-RU,ru;q=0.9'})
        self.cfg = cfg
        self.bucket = TokenBucket(cfg.rate_per_min, cfg.burst)
        if cookies_path:
            self._load_cookies(cookies_path)

    def _load_cookies(self, path: str):
        if not os.path.exists(path):
            log.warning('cookies.txt not found: %s', path)
            return
        try:
            cj = MozillaCookieJar()
            cj.load(path, ignore_discard=True, ignore_expires=True)
            for c in cj:
                self.s.cookies.set_cookie(c)
            log.info('Loaded %d cookies from %s', len(cj), path)
        except Exception:
            log.exception('Failed to load cookies from %s', path)

    def get(self, url: str, params: Optional[dict] = None, stop_event: Optional[threading.Event] = None) -> requests.Response:
        self.bucket.acquire(stop_event=stop_event)
        try:
            r = self.s.get(url, params=params, timeout=self.cfg.timeout, allow_redirects=True)
            return r
        except requests.RequestException as e:
            log.warning('Network error on GET %s: %s', url, e)
            raise

# ------------------------- Parsing stub -------------------------
PRICE_RE = re.compile(r"(\d[\d\s]{2,}\s?[₽Рр])")

def parse_listing(html: str) -> Dict[str, Any]:
    """Replace with your lawful parsing logic."""
    m = PRICE_RE.search(html)
    price_text = m.group(1) if m else None
    return {
        'found_price_text': price_text,
    }

# ------------------------- Excel I/O -------------------------
@dataclass
class Item:
    idx: int
    brand: str
    model: str
    buy_price: Optional[float]

    def query(self) -> str:
        parts = [str(self.brand or '').strip(), str(self.model or '').strip()]
        return ' '.join([p for p in parts if p])

def load_items_from_excel(path: str) -> List[Item]:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, 'rb') as f:
        content = f.read()
    df = pd.read_excel(io.BytesIO(content))

    def try_col(df, name, pos):
        if name in df.columns:
            return df[name]
        return df.iloc[:, pos]

    try:
        brand_col = try_col(df, 'A', 0)
    except Exception:
        brand_col = df.iloc[:, 0]
    try:
        model_col = try_col(df, 'B', 1)
    except Exception:
        model_col = df.iloc[:, 1]
    buy_col = None
    try:
        buy_col = try_col(df, 'C', 2)
    except Exception:
        pass

    items: List[Item] = []
    for i in range(len(df)):
        brand = str(brand_col.iloc[i]) if pd.notna(brand_col.iloc[i]) else ''
        model = str(model_col.iloc[i]) if pd.notna(model_col.iloc[i]) else ''
        buy = None
        if buy_col is not None and pd.notna(buy_col.iloc[i]):
            try:
                buy = float(str(buy_col.iloc[i]).replace(' ', '').replace(',', '.'))
            except Exception:
                buy = None
        if brand or model:
            items.append(Item(i, brand, model, buy))
    return items

# ------------------------- Worker -------------------------
@dataclass
class Result:
    idx: int
    query: str
    ok: bool
    data: Dict[str, Any]
    http_status: Optional[int] = None
    note: str = ''

def respectful_sleep(seconds: float, stop_event: Optional[threading.Event] = None):
    end = time.time() + seconds
    while time.time() < end:
        if stop_event is not None and stop_event.is_set():
            raise StopIteration
        time.sleep(0.1)

def backoff(attempt: int, retry_after: Optional[int] = None, stop_event: Optional[threading.Event] = None):
    if retry_after:
        delay = min(120, int(retry_after))
    else:
        delay = min(120, 2 ** min(6, attempt))
    log.info('Backoff: sleeping %s s', delay)
    respectful_sleep(delay, stop_event=stop_event)

def has_captcha(text: str) -> bool:
    return 'captcha' in text.lower() or 'капча' in text.lower()

def process_items(items: List[Item], client: AvitoClient, checkpoint: str = 'checkpoint.csv',
                  stop_event: Optional[threading.Event] = None, progress_cb=None) -> List[Result]:
    results: List[Result] = []
    done_idx: set[int] = set()

    # resume support
    if os.path.exists(checkpoint):
        try:
            prev = pd.read_csv(checkpoint)
            done_idx = set(prev['idx'].astype(int).tolist())
        except Exception:
            pass

    attempts: Dict[int, int] = {}

    total = len(items)
    processed = 0

    for it in items:
        if stop_event is not None and stop_event.is_set():
            break
        if it.idx in done_idx:
            processed += 1
            if progress_cb:
                progress_cb(processed, total, f"skip idx={it.idx}")
            continue

        q = it.query()
        url = client.cfg.base_url

        try:
            if progress_cb:
                progress_cb(processed, total, f"GET {url} q={q}")
            r = client.get(url, params={'q': q}, stop_event=stop_event)
            status = r.status_code
            if status == 200:
                text = r.text
                if has_captcha(text):
                    results.append(Result(it.idx, q, False, {}, http_status=status, note='captcha'))
                    attempts[it.idx] = attempts.get(it.idx, 0) + 1
                    backoff(attempts[it.idx], stop_event=stop_event)
                else:
                    data = parse_listing(text)
                    results.append(Result(it.idx, q, True, data, http_status=200))
            elif status in (401, 403):
                results.append(Result(it.idx, q, False, {}, http_status=status, note='access'))
                attempts[it.idx] = attempts.get(it.idx, 0) + 1
                backoff(attempts[it.idx], stop_event=stop_event)
            elif status in (429, 503):
                ra = r.headers.get('Retry-After')
                results.append(Result(it.idx, q, False, {}, http_status=status, note='rate'))
                attempts[it.idx] = attempts.get(it.idx, 0) + 1
                backoff(attempts[it.idx], int(ra) if ra and ra.isdigit() else None, stop_event=stop_event)
            else:
                results.append(Result(it.idx, q, False, {}, http_status=status, note='http'))
                respectful_sleep(1, stop_event=stop_event)
        except StopIteration:
            break
        except Exception as e:
            results.append(Result(it.idx, q, False, {}, http_status=None, note=str(e)))
            respectful_sleep(1, stop_event=stop_event)

        processed += 1
        if progress_cb:
            progress_cb(processed, total, f"processed idx={it.idx}")

        # checkpoint every 5
        if len(results) % 5 == 0 and results:
            _flush_checkpoint(results, checkpoint)

    _flush_checkpoint(results, checkpoint)
    return results

def _flush_checkpoint(results: List[Result], path: str):
    if not results:
        return
    rows = [{
        'idx': r.idx,
        'query': r.query,
        'ok': r.ok,
        'http_status': r.http_status,
        'note': r.note,
        **{f'data_{k}': v for k, v in (r.data or {}).items()},
    } for r in results]
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding='utf-8')

def dedupe_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    cand = path
    i = 1
    while os.path.exists(cand):
        cand = f"{base} ({i}){ext}"
        i += 1
    return cand

def save_output(results: List[Result], src_excel: str, out_base: Optional[str] = None) -> Tuple[str, str]:
    if out_base is None:
        stem, _ = os.path.splitext(os.path.basename(src_excel))
        out_base = f'{stem}_analyzed'
    csv_path = f"{out_base}.csv"
    xlsx_path = f"{out_base}.xlsx"
    csv_path = dedupe_path(csv_path)
    xlsx_path = dedupe_path(xlsx_path)

    rows = [{
        'idx': r.idx,
        'query': r.query,
        'ok': r.ok,
        'http_status': r.http_status,
        'note': r.note,
        **{f'data_{k}': v for k, v in (r.data or {}).items()},
    } for r in results]
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, encoding='utf-8')
    with pd.ExcelWriter(xlsx_path, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Results')
    return csv_path, xlsx_path
