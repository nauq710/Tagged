#!/usr/bin/env python3
"""Chromium smoke test: real browser upload -> shared Ready barrier -> PDF-independent JSON result.

Install:
    pip install playwright
    python -m playwright install chromium
Run after npm run build --prefix client:
    python tools/browser_e2e.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 18765
BASE = f'http://127.0.0.1:{PORT}'


def wait_for_server() -> None:
    for _ in range(100):
        try:
            with urlopen(BASE + '/health', timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('Browser test server did not become healthy')


def browser_case(browser, scenario_name: str, slots: list[str], mode: str = 'lockstep') -> None:
    scenario = ROOT / 'scenarios' / 'browser' / (scenario_name + '.input.json')
    expected_file = ROOT / 'scenarios' / 'browser' / (scenario_name + '.expected.json')
    expected = json.loads(expected_file.read_text())
    context = browser.new_context(viewport={'width': 1440, 'height': 980})
    pages = []
    try:
        for actor in slots:
            page = context.new_page()
            page.goto(BASE, wait_until='networkidle')
            page.locator('#sim-file').set_input_files(str(scenario))
            page.locator('#sim-actor').select_option(actor)
            page.locator('#sim-mode').select_option(mode)
            page.locator('#sim-run').fill('smoke-' + scenario_name + '-' + mode)
            page.locator('#sim-connect').click()
            page.locator('#sim-ready').wait_for(state='visible')
            page.wait_for_function("document.querySelector('#sim-ready').disabled === false")
            pages.append(page)

        # Start only after all tabs have connected. The test deliberately
        # prepares one browser first and checks the Ready barrier.
        pages[0].locator('#sim-ready').click()
        assert pages[0].locator('#sim-download').is_hidden()
        for page in pages[1:]:
            page.locator('#sim-ready').click()

        for page in pages:
            page.locator('#sim-download').wait_for(state='visible', timeout=25000)
            report = json.loads(page.locator('#sim-output').inner_text())
            assert report['mode'] == mode, report
            assert report['verdict'] == 'PASS', report
            assert report['expected'] == expected['expected']
            assert report['actual'] == expected['expected']
            assert report['scenario_sha256'] == expected['scenario_sha256']
            with page.expect_download() as download_info:
                page.locator('#sim-download').click()
            download = download_info.value
            file_path = download.path()
            assert file_path is not None
            assert json.loads(Path(file_path).read_text()) == report
        (ROOT / 'build').mkdir(exist_ok=True)
        pages[0].screenshot(
            path=str(ROOT / 'build' / f'{scenario_name}-{mode}.png'),
            full_page=True,
        )
        print(f'BROWSER_PASS {scenario_name} {mode}: {len(pages)} actual Chromium pages')
    finally:
        context.close()


def main() -> None:
    env = os.environ.copy()
    env['PORT'] = str(PORT)
    process = subprocess.Popen(
        [sys.executable, '-m', 'app.main'],
        cwd=ROOT / 'server',
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for_server()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            try:
                browser_case(browser, 'two_player_finish', ['alice', 'bob'])
                browser_case(browser, 'two_player_finish', ['alice', 'bob'], mode='realtime')
                browser_case(browser, 'late_join_finish', ['alice', 'bob', 'charlie'])
                browser_case(browser, 'credit_cloak_finish', ['alice', 'bob'])
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


if __name__ == '__main__':
    main()
