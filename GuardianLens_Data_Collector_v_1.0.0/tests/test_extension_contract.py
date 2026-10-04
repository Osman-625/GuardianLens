from __future__ import annotations

import json
import shutil
import subprocess

import pytest


def test_extension_manifest_scopes_manual_and_replay_permissions_to_supported_hosts(isolated):
    manifest = json.loads((isolated / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "alarms", "scripting", "storage", "tabs"}
    assert set(manifest["host_permissions"]) == {
        "http://127.0.0.1/*",
        "http://localhost/*",
        "https://carousell.com.my/*",
        "https://www.carousell.com.my/*",
        "https://mudah.my/*",
        "https://www.mudah.my/*",
    }
    serialized = json.dumps(manifest)
    assert "<all_urls>" not in serialized
    assert "https://*." not in serialized


def test_popup_has_accessible_async_status(isolated):
    from guardianlens.config import ROOT

    popup = (ROOT / "extension" / "popup.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in popup
    assert "<title>GuardianLens Capture</title>" in popup
    assert 'role="status"' in popup
    assert 'aria-live="polite"' in popup
    assert 'aria-atomic="true"' in popup


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is optional")
def test_popup_and_service_worker_reject_deceptive_local_server_urls(isolated):
    # conftest copies only manifest.json into the isolated extension tree.
    # Validation logic is read from the repository because it has no runtime-data dependency.
    from guardianlens.config import ROOT

    popup_path = ROOT / "extension" / "popup.js"
    background_path = ROOT / "extension" / "background.js"
    script = r"""
const popup = require(process.argv[1]);
const background = require(process.argv[2]);
const valid = [
  ['http://127.0.0.1:1', 'http://127.0.0.1:1'],
  ['http://localhost:80', 'http://localhost:80'],
  [' http://localhost:65535 ', 'http://localhost:65535'],
  ['http://127.0.0.1:8765/', 'http://127.0.0.1:8765'],
];
const invalid = [
  'http://127.0.0.1:0',
  'http://127.0.0.1:65536',
  'http://localhost',
  'http://localhost:8765/path',
  'http://localhost:8765?query=1',
  'http://user@localhost:8765',
  'http://localhost.evil.test:8765',
  'https://localhost:8765',
  'http://[::1]:8765',
];
for (const [input, expected] of valid) {
  if (popup.normalizeServer(input) !== expected) process.exit(11);
  if (background.normalizeLocalServer(input) !== expected) process.exit(12);
}
for (const input of invalid) {
  if (popup.normalizeServer(input) !== null) process.exit(21);
  if (background.normalizeLocalServer(input) !== null) process.exit(22);
}
const original = {id: 7, windowId: 3, url: 'https://www.mudah.my/test-123456.htm'};
if (!background.tabSnapshotMatches({...original}, original, original.url)) process.exit(31);
if (background.tabSnapshotMatches({...original, id: 8}, original, original.url)) process.exit(32);
if (background.tabSnapshotMatches({...original, url: 'https://www.mudah.my/other-999999.htm'}, original, original.url)) process.exit(33);
const detail = background.safeApiErrorDetail(
  [{loc: ['body', 'page_title'], msg: 'String should have at most 500 characters'}],
  'fallback',
);
if (!detail.includes('page_title') || detail.includes('[object Object]')) process.exit(34);
"""
    result = subprocess.run(
        ["node", "-e", script, str(popup_path), str(background_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is optional")
def test_image_directory_key_groups_gallery_photos_and_excludes_other_folders():
    # collectPageData() uses this to trust small gallery thumbnails (some listing sites render
    # every photo but the selected one far under the 160px floor) without trusting arbitrary small
    # images elsewhere on the page, by requiring they share a CDN folder with an already-qualified
    # full-size photo.
    from guardianlens.config import ROOT

    background_path = ROOT / "extension" / "background.js"
    script = r"""
const background = require(process.argv[1]);
const key = background.imageDirectoryKey;
const mainPhoto = key('https://cdn.rnudah.com/images/plain/96a782bdec083ed7ab6c85e-2999038366139536864.jpg');
const thumbnail = key('https://cdn.rnudah.com/images/plain/b5e7b6d4a571a3e24542c9-2999033887719151072.jpg?w=80');
const unrelatedGrid = key('https://cdn.rnudah.com/grids/plain/96a782bdec083ed7ab6c85e-2999038366139536864.jpg');
const differentHost = key('https://mcdn.mudah.my/images/plain/96a782bdec083ed7ab6c85e-2999038366139536864.jpg');
const upperCaseHost = key('https://CDN.rnudah.com/images/plain/other-file.jpg');
if (mainPhoto !== thumbnail) process.exit(11);
if (mainPhoto === unrelatedGrid) process.exit(12);
if (mainPhoto === differentHost) process.exit(13);
if (mainPhoto !== upperCaseHost) process.exit(14);
if (key('not a url') !== null) process.exit(15);
if (key('') !== null) process.exit(16);
"""
    result = subprocess.run(
        ["node", "-e", script, str(background_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is optional")
def test_collect_visible_text_is_exported_for_seller_capture():
    # collectVisibleText is injected into the seller/profile tab via chrome.scripting.executeScript
    # (same mechanism as collectPageData for the listing page); this only asserts it is present and
    # exported for that injection, since document/location are unavailable outside a real page.
    from guardianlens.config import ROOT

    background_path = ROOT / "extension" / "background.js"
    script = r"""
const background = require(process.argv[1]);
if (typeof background.collectVisibleText !== 'function') process.exit(41);
"""
    result = subprocess.run(
        ["node", "-e", script, str(background_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is optional")
def test_replay_page_states_are_explicit_and_manual_capture_helper_remains():
    from guardianlens.config import ROOT

    background_path = ROOT / "extension" / "background.js"
    script = r"""
const background = require(process.argv[1]);
const valid = {
  source_url: 'https://www.carousell.com.my/p/example-123456/',
  page_state: 'candidate',
  image_urls: ['https://images.example.test/item.jpg'],
  listing_evidence: {h1_text: 'Example phone', has_price_signal: true},
};
if (background.capturePageState(valid, 'carousell') !== 'ready') process.exit(51);
if (background.capturePageState({...valid, page_state: 'captcha'}, 'carousell') !== 'captcha') process.exit(52);
if (background.capturePageState({...valid, page_state: 'login_required'}, 'carousell') !== 'login_required') process.exit(53);
if (background.capturePageState({...valid, page_state: 'listing_unavailable'}, 'carousell') !== 'listing_unavailable') process.exit(54);
if (background.capturePageState({...valid, source_url: 'https://www.mudah.my/example-123456.htm'}, 'carousell') !== 'invalid_listing_page') process.exit(55);
if (background.classifyCaptureFailure(new Error('Timed out waiting')).status !== 'capture_timeout') process.exit(56);
if (background.classifyCaptureFailure(new Error('Cloudflare access denied')).status !== 'access_denied') process.exit(57);
"""
    result = subprocess.run(
        ["node", "-e", script, str(background_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    source = background_path.read_text(encoding="utf-8")
    assert "guardianlens.capture'" in source
    assert "guardianlens.captureSeller'" in source
    assert "'/api/replay/claim'" in source
    assert "captureListingTab" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is optional")
def test_extension_background_js_syntax_is_valid():
    from guardianlens.config import ROOT

    result = subprocess.run(
        ["node", "--check", str(ROOT / "extension" / "background.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
