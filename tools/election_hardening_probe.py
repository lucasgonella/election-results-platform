"""Read-only, rate/budget limited Chromium probe; never targets TSE hosts."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlsplit


async def probe(args):
    from playwright.async_api import async_playwright
    origin = urlsplit(args.url)
    allowed = {'127.0.0.1', 'localhost'}
    if args.public: allowed.add('afgnet.com.br')
    if origin.hostname not in allowed or origin.scheme not in {'http', 'https'}:
        raise ValueError('Only loopback or explicitly authorized public portal is allowed')
    if args.public and (args.sessions > 4 or args.rps > 8 or args.duration > 90 or args.budget > 400 or args.burst > 64):
        raise ValueError('Public probe exceeds fixed safety limits')
    if args.sessions < 1 or args.rps <= 0 or args.duration < 1 or args.budget < 1 or args.burst < 1: raise ValueError('Invalid limits')
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    lock, halt = asyncio.Lock(), asyncio.Event()
    sent, credited_at, tokens = 0, started, float(args.burst)
    trace, failures, pages_report = [], [], []
    reason = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        contexts = []
        async def route(request_route):
            nonlocal sent, credited_at, tokens, reason
            request = request_route.request
            if urlsplit(request.url).netloc != origin.netloc or request.method not in {'GET', 'HEAD'}:
                return await request_route.abort()
            async with lock:
                if halt.is_set() or sent >= args.budget:
                    if sent >= args.budget: reason = 'request_budget'; halt.set()
                    return await request_route.abort()
                instant = time.monotonic()
                tokens = min(args.burst, tokens + (instant - credited_at) * args.rps)
                credited_at = instant
                if tokens < 1:
                    await asyncio.sleep((1 - tokens) / args.rps)
                    instant = time.monotonic()
                    tokens = min(args.burst, tokens + (instant - credited_at) * args.rps)
                    credited_at = instant
                if halt.is_set(): return await request_route.abort()
                sent += 1; tokens -= 1
            await request_route.continue_()
        async def response(res, session_id):
            nonlocal reason
            if urlsplit(res.url).netloc != origin.netloc: return
            headers = res.headers
            timing = res.request.timing
            elapsed = timing['responseStart'] - timing['requestStart'] if timing['responseStart'] >= 0 and timing['requestStart'] >= 0 else None
            entry = {'session': session_id, 'at_seconds': round(time.monotonic() - started, 4), 'url': res.url,
                'response_headers_ms': elapsed,
                'status': res.status, 'headers': {k: headers[k] for k in ['server', 'cache-control', 'etag',
                'last-modified', 'retry-after', 'x-cache', 'age', 'x-ratelimit-limit', 'x-ratelimit-remaining',
                'content-length', 'via', 'cf-cache-status', 'x-powered-by'] if k in headers}}
            trace.append(entry)
            if res.status == 429 or res.status >= 500:
                reason = 'http_' + str(res.status); halt.set()
                try: entry['error_body_excerpt'] = (await res.text())[:1500]
                except Exception: pass
        async def session(index):
            context = await browser.new_context(viewport={'width': 390 if index % 2 else 1440, 'height': 900},
                locale='pt-BR', timezone_id='America/Sao_Paulo')
            contexts.append(context)
            await context.route('**/*', route)
            page = await context.new_page()
            async def on_response(res): await response(res, index)
            page.on('response', on_response)
            page.on('pageerror', lambda error: failures.append(str(error)))
            try:
                await page.goto(args.url, wait_until='domcontentloaded', timeout=90000)
                await page.wait_for_function('window.ElectionPortal?.getContext()?.result?.candidates?.length > 0', timeout=90000)
                pages_report.append({'session': index, 'initial_seconds': round(time.monotonic() - started, 4)})
            except Exception as error:
                if not halt.is_set(): failures.append(type(error).__name__)
            return page
        tasks = [asyncio.create_task(session(i)) for i in range(args.sessions)]
        try: await asyncio.wait_for(halt.wait(), timeout=args.duration)
        except asyncio.TimeoutError: reason = 'duration_complete'
        halt.set()
        for task in tasks:
            if task.done() and not task.cancelled():
                page = task.result()
                try:
                    state = await page.evaluate('''() => ({round:window.ElectionPortal?.getContext()?.round,
                        snapshot:window.ElectionPortal?.getContext()?.version?.snapshot_id,
                        liveData:window.LiveData?.stats, liveMetrics:window.ElectionLiveMetrics,
                        status:document.getElementById('live-status-label')?.textContent})''')
                    pages_report.append(state)
                except Exception: pass
            else: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()
    duration = time.monotonic() - started
    return {'started_at': started_utc, 'finished_at': datetime.now(timezone.utc).isoformat(), 'url': args.url,
        'limits': {'sessions': args.sessions, 'steady_rps': args.rps, 'initial_burst_requests': args.burst, 'seconds': args.duration, 'requests': args.budget},
        'stop_reason': reason, 'duration_seconds': round(duration, 3), 'requests_sent': sent,
        'average_rps': round(sent / duration, 3), 'statuses': dict(Counter(x['status'] for x in trace)),
        'page_errors': failures, 'pages': pages_report, 'trace': trace}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--public', action='store_true')
    p.add_argument('--sessions', type=int, default=1)
    p.add_argument('--rps', type=float, default=8)
    p.add_argument('--burst', type=int, default=1)
    p.add_argument('--duration', type=int, default=60)
    p.add_argument('--budget', type=int, default=300)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = asyncio.run(probe(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'trace'}, ensure_ascii=False))


if __name__ == '__main__': main()
