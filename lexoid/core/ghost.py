"""
Ghost browsing for URL parsing.

This module provides an *opt-in*, agentic-browser-style way to fetch web pages
for parsing. It layers three independently-useful capabilities on top of the
default Playwright fetch in ``lexoid.core.utils.get_webpage_soup``:

1. **Bot-detection bypass (stealth):** drive a stealthy browser (via the
   ``patchright`` drop-in when available, else hand-rolled init-script patches)
   so Cloudflare/DataDome-protected pages can be read.
2. **Reliable JS rendering:** ``networkidle`` waits, auto-scroll for lazy-load,
   and optional ``wait_for_selector`` so dynamic SPA content is captured.
3. **Agentic navigation (optional):** a vision-LLM loop that clicks/scrolls/
   navigates to reach gated content before extraction, reusing lexoid's
   existing LLM plumbing (``create_response``). Page state is grounded with
   *set-of-marks* prompting — numbered boxes drawn over interactive elements on
   the screenshot, so the model's chosen index matches a real element (an
   approach used by Microsoft AutoGen's MultimodalWebSurfer).

Browser acquisition supports three auto-selected modes:

- ``cdp``: attach to an already-running real browser (e.g. Chrome started with
  ``--remote-debugging-port``) over the Chrome DevTools Protocol. This is the
  truest "ghost" — it reuses the real profile, cookies, fingerprint and
  logged-in sessions. Configured via ``LEXOID_CDP_URL``.
- ``persistent``: launch a browser with a stable ``user_data_dir`` so cookies
  and fingerprint persist across runs.
- ``fresh``: launch a throwaway stealth browser (closest to the legacy path).

Everything here is gated behind an explicit ``ghost`` opt-in so the default
parsing path is unchanged. ``ghost_get_html`` returns ``None`` on any failure
so callers transparently fall back to the legacy fetch / ``requests.get``.
"""

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

import nest_asyncio
from loguru import logger

# Default launch args for ghost browser launches (persistent/fresh modes).
# Note: when using patchright, it manages most anti-automation tweaks itself;
# we deliberately avoid "--disable-blink-features=AutomationControlled" there.
_GHOST_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--window-size=1920,1080",
]

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Hand-rolled stealth patches, applied via add_init_script only when patchright
# is NOT available (and never in CDP mode, where the real browser already has a
# genuine fingerprint).
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = window.chrome || {runtime: {}};
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : originalQuery(parameters)
  );
}
"""

# Collects up to `cap` visible, interactive elements with a stable selector, a
# viewport-relative bounding box, and whether the element is currently in the
# viewport. The bounding box drives set-of-marks annotation; `in_viewport` lets
# the prompt distinguish on-screen targets from ones that need scrolling
# (mirroring AutoGen's visible / off-screen element split).
_COLLECT_ELEMENTS_JS = """
(cap) => {
  // Clear stale handles from a previous step before re-tagging.
  document.querySelectorAll('[data-lexoid-uid]').forEach(e => e.removeAttribute('data-lexoid-uid'));
  const sel = 'a, button, input, textarea, select, summary, '
    + '[role=button], [role=link], [role=option], [role=menuitem], '
    + '[role=menuitemradio], [role=menuitemcheckbox], [role=tab], [role=switch], '
    + '[role=checkbox], [role=radio], [role=treeitem], [role=combobox], [onclick]';
  const nodes = Array.from(document.querySelectorAll(sel));
  const vh = window.innerHeight, vw = window.innerWidth;
  const out = [];
  for (const el of nodes) {
    if (out.length >= cap) break;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (rect.width === 0 || rect.height === 0) continue;
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    if (rect.bottom < 0 || rect.top > vh * 3) continue;  // skip far off-screen
    // Tag each element with a unique handle so a chosen index maps to exactly
    // one element (generated CSS paths like 'div > button:nth-child(2)' are not
    // unique and cause clicks to hit the wrong element).
    const uid = out.length;
    el.setAttribute('data-lexoid-uid', uid);
    const selector = '[data-lexoid-uid="' + uid + '"]';
    const text = (el.innerText || el.value || el.getAttribute('aria-label')
      || el.getAttribute('placeholder') || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 80);
    const inViewport = rect.top < vh && rect.bottom > 0 && rect.left < vw && rect.right > 0;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      input_type: (el.getAttribute('type') || '').toLowerCase(),
      text,
      selector,
      in_viewport: inViewport,
      rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
    });
  }
  return out;
}
"""

# Draws numbered boxes over interactive elements (set-of-marks prompting) so the
# vision model can map a chosen index to a concrete element. Boxes are layered in
# a single overlay container that is removed again before content extraction.
_SET_OF_MARKS_JS = """
(marks) => {
  const old = document.getElementById('lexoid-som');
  if (old) old.remove();
  const root = document.createElement('div');
  root.id = 'lexoid-som';
  root.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;';
  for (const m of marks) {
    const box = document.createElement('div');
    box.style.cssText =
      'position:fixed;border:2px solid #FF007F;box-sizing:border-box;' +
      'left:' + m.x + 'px;top:' + m.y + 'px;width:' + m.w + 'px;height:' + m.h + 'px;';
    const label = document.createElement('div');
    label.textContent = m.i;
    label.style.cssText =
      'position:fixed;background:#FF007F;color:#fff;font:bold 11px monospace;' +
      'padding:0 3px;left:' + m.x + 'px;top:' + Math.max(0, m.y - 14) + 'px;';
    root.appendChild(box);
    root.appendChild(label);
  }
  document.body.appendChild(root);
}
"""

_REMOVE_MARKS_JS = """
() => { const n = document.getElementById('lexoid-som'); if (n) n.remove(); }
"""

# Remove the element handles we set so they never leak into extracted HTML.
_CLEAR_UIDS_JS = """
() => document.querySelectorAll('[data-lexoid-uid]').forEach(e => e.removeAttribute('data-lexoid-uid'))
"""


@dataclass
class GhostConfig:
    """Resolved configuration for a ghost-browsing fetch."""

    enabled: bool = False
    cdp_url: Optional[str] = None
    user_data_dir: Optional[str] = None
    headless: bool = True
    stealth: bool = True
    timeout_ms: int = 30000
    wait_until: str = "networkidle"  # domcontentloaded | load | networkidle
    wait_for_selector: Optional[str] = None
    auto_scroll: bool = True
    scroll_max_rounds: int = 15
    user_agent: str = _DEFAULT_USER_AGENT
    # Agentic navigation
    navigate: bool = False
    nav_instruction: Optional[str] = None
    nav_model: Optional[str] = None
    nav_max_steps: int = 8
    set_of_marks: bool = True  # annotate screenshots with numbered element boxes
    screenshot_max_dim: int = 1280  # downscale screenshots before sending to the LLM
    nav_history_steps: int = 5  # recent actions fed back into the prompt
    nav_same_domain: bool = True  # restrict agent navigation to the start site

    @classmethod
    def from_kwargs(cls, ghost_opts) -> "GhostConfig":
        """
        Build a config from the ``ghost`` kwarg (bool or dict) plus env vars.

        Returns an ``enabled=False`` config when nothing requests ghost mode, so
        callers keep the legacy behaviour by default.
        """
        opts: dict = {}
        if isinstance(ghost_opts, dict):
            opts = dict(ghost_opts)
        explicit = bool(ghost_opts)

        env_cdp = os.getenv("LEXOID_CDP_URL")
        env_profile = os.getenv("LEXOID_GHOST_PROFILE_DIR")
        env_flag = os.getenv("LEXOID_GHOST", "").lower() in ("1", "true", "yes")

        cdp_url = opts.get("cdp_url", env_cdp)
        user_data_dir = opts.get("user_data_dir", env_profile)

        enabled = bool(explicit or env_flag or cdp_url)
        if not enabled:
            return cls(enabled=False)

        def pick(key, default):
            return opts.get(key, default)

        return cls(
            enabled=True,
            cdp_url=cdp_url,
            user_data_dir=user_data_dir,
            headless=pick("headless", True),
            stealth=pick("stealth", True),
            timeout_ms=int(pick("timeout_ms", 30000)),
            wait_until=pick("wait_until", "networkidle"),
            wait_for_selector=pick("wait_for_selector", None),
            auto_scroll=pick("auto_scroll", True),
            scroll_max_rounds=int(pick("scroll_max_rounds", 15)),
            user_agent=pick("user_agent", _DEFAULT_USER_AGENT),
            navigate=bool(pick("navigate", False)),
            nav_instruction=pick("nav_instruction", None),
            nav_model=pick("nav_model", None),
            nav_max_steps=int(pick("nav_max_steps", 8)),
            set_of_marks=bool(pick("set_of_marks", True)),
            screenshot_max_dim=int(pick("screenshot_max_dim", 1280)),
            nav_history_steps=int(pick("nav_history_steps", 5)),
            nav_same_domain=bool(pick("nav_same_domain", True)),
        )

    def for_child(self) -> "GhostConfig":
        """Config for recursively-crawled child URLs: never run the agentic loop."""
        return replace(self, navigate=False, nav_instruction=None)


def _get_async_playwright(cfg: GhostConfig):
    """
    Return an ``async_playwright`` factory and whether patchright is in use.

    Prefers patchright (stronger anti-detection) when stealth is requested and
    the package is installed; otherwise falls back to stock playwright.
    """
    if cfg.stealth:
        try:
            from patchright.async_api import async_playwright

            return async_playwright, True
        except ImportError:
            logger.debug(
                "patchright not installed; falling back to playwright + init-script stealth"
            )
    from playwright.async_api import async_playwright

    return async_playwright, False


@asynccontextmanager
async def acquire_page(p, cfg: GhostConfig, patchright_active: bool):
    """
    Yield ``(page, mode)`` for the resolved acquisition mode, handling per-mode
    teardown. ``mode`` is one of ``"cdp"``, ``"persistent"``, ``"fresh"``.

    Teardown semantics differ critically by mode:
      - cdp: close ONLY the tab we opened; never close the user's browser/context.
      - persistent: close the launched persistent context.
      - fresh: close the launched browser.
    """
    if cfg.cdp_url:
        # CDP attach — reuse the existing real context; do not create a new one.
        browser = await p.chromium.connect_over_cdp(cfg.cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        try:
            yield page, "cdp"
        finally:
            try:
                await page.close()
            except Exception:
                pass

    elif cfg.user_data_dir:
        # Persistent stealth context — cookies/fingerprint persist across runs.
        context = await p.chromium.launch_persistent_context(
            user_data_dir=cfg.user_data_dir,
            headless=cfg.headless,
            args=_GHOST_LAUNCH_ARGS,
            user_agent=cfg.user_agent,
            viewport={"width": 1920, "height": 1080},
            bypass_csp=True,
        )
        if cfg.stealth and not patchright_active:
            await context.add_init_script(_STEALTH_INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            yield page, "persistent"
        finally:
            try:
                await context.close()
            except Exception:
                pass

    else:
        # Fresh stealth launch — throwaway browser, closest to the legacy path.
        browser = await p.chromium.launch(
            headless=cfg.headless,
            args=_GHOST_LAUNCH_ARGS,
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=cfg.user_agent,
            bypass_csp=True,
        )
        if cfg.stealth and not patchright_active:
            await context.add_init_script(_STEALTH_INIT_SCRIPT)
        page = await context.new_page()
        try:
            yield page, "fresh"
        finally:
            try:
                await browser.close()
            except Exception:
                pass


async def _settle(page, cfg: GhostConfig):
    """Best-effort wait for the page to finish rendering."""
    try:
        await page.wait_for_load_state(cfg.wait_until, timeout=cfg.timeout_ms)
    except Exception:
        # networkidle can time out on streaming/websocket sites; degrade gracefully.
        logger.debug(f"wait_for_load_state({cfg.wait_until}) timed out; continuing")


async def _auto_scroll(page, cfg: GhostConfig):
    """Scroll to the bottom in steps to trigger lazy-loaded / infinite content."""
    previous_height = -1
    for _ in range(cfg.scroll_max_rounds):
        try:
            height = await page.evaluate("document.body.scrollHeight")
        except Exception:
            break
        if height == previous_height:
            break
        previous_height = height
        try:
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
        except Exception:
            break
        await asyncio.sleep(0.4)


async def render_page(page, url: str, cfg: GhostConfig) -> str:
    """Navigate to ``url``, render reliably, and return the page HTML."""
    await page.goto(url, wait_until="domcontentloaded", timeout=cfg.timeout_ms)
    await _settle(page, cfg)
    if cfg.auto_scroll:
        await _auto_scroll(page, cfg)
    if cfg.wait_for_selector:
        try:
            await page.wait_for_selector(cfg.wait_for_selector, timeout=cfg.timeout_ms)
        except Exception:
            logger.debug(f"wait_for_selector({cfg.wait_for_selector!r}) timed out")
    return await page.content()


# --------------------------------------------------------------------------- #
# Agentic navigation
# --------------------------------------------------------------------------- #

_NAV_SYSTEM_PROMPT = """You are a web-navigation agent. Your goal is to interact with a web page until the content described by the INSTRUCTION is visible, then stop.

You are given a screenshot of the current viewport with numbered pink boxes drawn over the interactive elements (set-of-marks), and a matching numbered list of those elements. The number on a box is the element's index. You also see RECENT ACTIONS — do NOT repeat an action that made no progress.

Choose EXACTLY ONE next action and respond with ONLY a JSON object (no prose, no code fences):
{"action": "click"|"type"|"select"|"keypress"|"hover"|"scroll"|"navigate"|"back"|"refresh"|"wait"|"done", "index": <int>, "text": <str>, "keys": <str>, "url": <str>, "direction": "up"|"down", "reason": <str>}

Rules:
- "index" refers to a box number from the list (for click/type/select/hover). Only use indices that exist.
- Elements marked (off-screen) are not visible yet; "scroll" toward them first.
- "type" fills an input with "text" but does NOT submit; to submit a form, then "click" the submit button (or "keypress" "Enter"). "keypress" presses "keys" (e.g. "Enter").
- "select" picks an option from ANY dropdown — a native <select> OR an autocomplete/combobox (role=combobox). Put the desired option text in "text"; the field is opened, filtered, and the matching option clicked for you. Do NOT "scroll" a long dropdown hunting for an option — use "select".
- "scroll" takes "direction" ("down" by default); "navigate" takes "url"; "back"/"refresh" need no other fields.
- NEVER type into password/credential fields and never submit login forms.
- Use "done" as soon as the target content is on screen. Prefer the fewest steps."""


def _downscale_png(png: bytes, max_dim: int) -> bytes:
    """Resize a PNG so its largest side is <= max_dim (cost + model image limits)."""
    if not png or max_dim <= 0:
        return png
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(png))
        if max(img.size) <= max_dim:
            return png
        img.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return png


def _same_site(url_a: str, url_b: str) -> bool:
    """True if both URLs share a registrable domain (last two host labels)."""
    from urllib.parse import urlparse

    def base(u: str) -> str:
        host = (urlparse(u).hostname or "").lower()
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    return base(url_a) == base(url_b)


def _normalize_step_usage(usage: Optional[dict]) -> dict:
    """
    Normalize ``create_response`` usage to ``{"input", "output", "total"}``.

    ``create_response`` is inconsistent across providers: Gemini returns
    ``{"input", "output", "total"}`` while OpenAI/Anthropic/etc. return
    ``{"input_tokens", "output_tokens", "total_tokens"}``. Accept either.
    """
    usage = usage or {}
    inp = usage.get("input", usage.get("input_tokens", 0)) or 0
    out = usage.get("output", usage.get("output_tokens", 0)) or 0
    total = usage.get("total", usage.get("total_tokens", 0)) or 0
    if not total:
        total = inp + out
    return {"input": inp, "output": out, "total": total}


async def _collect_elements(page, cap: int = 40) -> List[dict]:
    try:
        return await page.evaluate(_COLLECT_ELEMENTS_JS, cap)
    except Exception:
        return []


def _parse_action(raw: str) -> Optional[dict]:
    """Parse the LLM's JSON action, tolerating code fences / surrounding prose."""
    if not raw:
        return None
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1] if text.count("```") >= 2 else text
        text = text.replace("json", "", 1).strip()
    # Narrow to the outermost JSON object if there's surrounding prose.
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        return json.loads(text)
    except Exception:
        try:
            import ast

            return ast.literal_eval(text)
        except Exception:
            logger.debug(f"Could not parse navigation action: {raw!r}")
            return None


def _format_element(index: int, el: dict) -> str:
    """One numbered line describing an interactive element for the prompt."""
    role = f" role={el['role']}" if el.get("role") else ""
    offscreen = "" if el.get("in_viewport", True) else " (off-screen)"
    return f"[{index}] <{el['tag']}{role}>{offscreen} {el['text']}"


async def _screenshot_with_marks(page, elements, cfg: GhostConfig) -> bytes:
    """
    Screenshot the viewport, optionally with set-of-marks boxes drawn over the
    in-viewport interactive elements (indices match the prompt's element list).
    The overlay is always removed afterwards so it never leaks into extraction.
    """
    drew = False
    if cfg.set_of_marks:
        marks = [
            {"i": i, **{k: e["rect"][k] for k in ("x", "y", "w", "h")}}
            for i, e in enumerate(elements)
            if e.get("in_viewport") and e.get("rect")
        ]
        if marks:
            try:
                await page.evaluate(_SET_OF_MARKS_JS, marks)
                drew = True
            except Exception:
                drew = False
    try:
        png = await page.screenshot()
    except Exception:
        png = b""
    if drew:
        try:
            await page.evaluate(_REMOVE_MARKS_JS)
        except Exception:
            pass
    return _downscale_png(png, cfg.screenshot_max_dim)


async def _execute_action(page, cfg, action, elements, start_url):
    """
    Execute one parsed action against the page. Returns ``(page, outcome)``;
    ``page`` may change when an action opens a new tab we switch to.
    """
    kind = str(action.get("action", "")).lower()
    idx = action.get("index")
    el = (
        elements[int(idx)]
        if idx is not None and 0 <= int(idx) < len(elements)
        else None
    )
    # Track tab count so we can follow popups opened by the action.
    context = getattr(page, "context", None)
    allow_tab_switch = context is not None and not cfg.cdp_url
    pages_before = len(context.pages) if allow_tab_switch else None

    outcome = "ok"
    try:
        if kind == "click" and el:
            await page.click(el["selector"], timeout=cfg.timeout_ms)
        elif kind == "type" and el:
            if el.get("input_type") == "password":
                outcome = "blocked: password field"  # never type credentials
            else:
                # Focus + key-by-key typing (not fill): triggers React onChange
                # and segmented/auto-advancing inputs (e.g. one box per digit).
                # Does NOT auto-submit, so multi-field forms work.
                text = str(action.get("text", ""))
                try:
                    await page.click(el["selector"], timeout=cfg.timeout_ms)
                except Exception:
                    await page.focus(el["selector"])
                await page.keyboard.type(text, delay=20)
        elif kind == "select" and el:
            value = str(action.get("text", ""))
            if el.get("tag") == "select":
                # Native <select>.
                try:
                    await page.select_option(el["selector"], label=value)
                except Exception:
                    await page.select_option(el["selector"], value=value)
            else:
                # Custom dropdown / autocomplete (e.g. react-select): open it, type
                # to filter (long lists never fit on screen), then click the
                # matching role=option. Done in one action so the LLM can't get
                # stuck scrolling a 250-item list.
                await page.click(el["selector"], timeout=cfg.timeout_ms)
                if value:
                    try:
                        await page.keyboard.type(value, delay=20)
                    except Exception:
                        pass
                await asyncio.sleep(0.4)  # let options filter/render
                opt_sel = await page.evaluate(
                    "(val) => {"
                    "  const opts = Array.from(document.querySelectorAll('[role=option]'));"
                    "  const v = (val || '').toLowerCase();"
                    "  const t = opts.find(o => (o.innerText || '').toLowerCase().includes(v)) || opts[0];"
                    "  if (!t) return null;"
                    "  if (!t.id) t.id = 'lexoid-opt-tmp';"
                    "  return '#' + CSS.escape(t.id);"
                    "}",
                    value,
                )
                if opt_sel:
                    await page.click(opt_sel, timeout=cfg.timeout_ms)
                    outcome = "select(combobox) ok"
                else:
                    outcome = "select: no matching option"
        elif kind == "hover" and el:
            await page.hover(el["selector"], timeout=cfg.timeout_ms)
        elif kind == "keypress":
            keys = action.get("keys") or action.get("text")
            if keys:
                await page.keyboard.press(str(keys))
        elif kind == "scroll":
            sign = -1 if str(action.get("direction", "down")).lower() == "up" else 1
            await page.evaluate(f"window.scrollBy(0, {sign} * window.innerHeight)")
        elif kind == "navigate" and action.get("url"):
            target = action["url"]
            if cfg.nav_same_domain and not _same_site(target, start_url):
                outcome = "blocked: cross-domain"
            else:
                await page.goto(
                    target, wait_until="domcontentloaded", timeout=cfg.timeout_ms
                )
        elif kind == "back":
            await page.go_back(timeout=cfg.timeout_ms)
        elif kind == "refresh":
            await page.reload(timeout=cfg.timeout_ms)
        elif kind == "wait":
            pass
        else:
            outcome = "no-op (bad action/index)"
    except Exception as e:
        outcome = f"failed: {e}"
        logger.debug(f"Ghost navigation action {kind} failed: {e}")

    # New-tab/popup handling: follow a tab the action opened so the parser
    # doesn't lose the content. Cross-domain popups are closed when same_domain.
    if pages_before is not None and len(context.pages) > pages_before:
        new_page = context.pages[-1]
        try:
            await new_page.wait_for_load_state("domcontentloaded", timeout=cfg.timeout_ms)
        except Exception:
            pass
        if cfg.nav_same_domain and new_page.url and not _same_site(new_page.url, start_url):
            try:
                await new_page.close()
            except Exception:
                pass
            outcome += " (blocked cross-domain tab)"
        else:
            page = new_page
            outcome += " (switched to new tab)"

    return page, outcome


async def _run_agentic_navigation(page, cfg: GhostConfig, start_url=None):
    """
    Drive the page toward ``cfg.nav_instruction`` using an LLM action loop, so
    the instructed content can be extracted.

    Returns ``(usage, page)`` — accumulated token usage and the active page
    (which may differ from the input if a new tab was followed). Logs each
    action for auditability. Best effort: any failure ends the loop and
    extraction proceeds.
    """
    # Imported lazily to avoid pulling the LLM stack into the default path.
    from lexoid.core.parse_type.llm_parser import create_response
    from lexoid.core.utils import DEFAULT_LLM, get_api_provider_for_model

    model = cfg.nav_model or DEFAULT_LLM
    try:
        api = get_api_provider_for_model(model)
    except ValueError:
        logger.warning(f"Ghost navigation: unsupported model {model!r}; skipping")
        return {"input": 0, "output": 0, "total": 0}, page

    start_url = start_url or page.url
    usage = {"input": 0, "output": 0, "total": 0}
    history: List[str] = []
    last_sig = None
    stall = 0

    for step in range(cfg.nav_max_steps):
        elements = await _collect_elements(page)
        listing = "\n".join(_format_element(i, e) for i, e in enumerate(elements))
        png = await _screenshot_with_marks(page, elements, cfg)
        image_url = (
            "data:image/png;base64," + base64.b64encode(png).decode("utf-8")
            if png
            else None
        )
        title = await page.title()

        # No-progress / loop detection: stop if the page state hasn't changed.
        sig = (page.url, title, tuple(e.get("text", "") for e in elements[:15]))
        if sig == last_sig:
            stall += 1
            if stall >= 2:
                logger.info("Ghost navigation: no progress for 2 steps; stopping")
                break
        else:
            stall = 0
        last_sig = sig

        recent = "\n".join(history[-cfg.nav_history_steps :]) or "(none yet)"
        state = (
            f"INSTRUCTION: {cfg.nav_instruction}\n"
            f"URL: {page.url}\nTITLE: {title}\n"
            f"RECENT ACTIONS:\n{recent}\n"
            f"INTERACTIVE ELEMENTS:\n{listing}\n"
        )
        # gemini's create_response path uses only system_prompt; others use
        # user_prompt. Pass the combined context to both for portability.
        combined = _NAV_SYSTEM_PROMPT + "\n\n" + state
        try:
            result = create_response(
                api=api,
                model=model,
                system_prompt=combined,
                user_prompt=combined,
                image_url=image_url,
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as e:
            logger.warning(f"Ghost navigation step {step} LLM call failed: {e}")
            break

        step_usage = _normalize_step_usage(result.get("usage"))
        for k in usage:
            usage[k] += step_usage[k]

        action = _parse_action(result.get("response", ""))
        if not action:
            break
        kind = str(action.get("action", "")).lower()
        logger.info(
            f"Ghost navigation step {step}: {kind} {action.get('reason', '')}".strip()
        )
        if kind == "done":
            break

        page, outcome = await _execute_action(page, cfg, action, elements, start_url)
        await _settle(page, cfg)

        detail = []
        if action.get("index") is not None:
            detail.append(f"idx={action['index']}")
        if action.get("url"):
            detail.append(f"url={action['url']}")
        if action.get("direction"):
            detail.append(f"dir={action['direction']}")
        history.append(
            f"step {step}: {kind} {' '.join(detail)} -> {outcome}".replace("  ", " ")
        )

    try:
        await page.evaluate(_CLEAR_UIDS_JS)  # keep handles out of extracted HTML
    except Exception:
        pass
    return usage, page


# --------------------------------------------------------------------------- #
# Sync entry point
# --------------------------------------------------------------------------- #


def ghost_get_html(url: str, cfg: GhostConfig) -> Tuple[Optional[str], dict]:
    """
    Fetch ``url`` using ghost browsing.

    Returns ``(html, token_usage)`` where ``token_usage`` is in lexoid's
    top-level shape (``{"input", "output", "total"}``) and accounts for the
    agentic-navigation LLM calls (zeros when navigation did not run). ``html``
    is ``None`` on any failure so the caller can fall back to the legacy fetch /
    ``requests.get`` path.
    """
    empty_usage = {"input": 0, "output": 0, "total": 0}
    if not cfg.enabled:
        return None, empty_usage

    nest_asyncio.apply()
    async_playwright, patchright_active = _get_async_playwright(cfg)
    # Stealth init-scripts are never applied in CDP mode (real fingerprint).
    if cfg.cdp_url:
        patchright_active = True  # suppress manual init-script injection

    async def _run() -> Tuple[str, dict]:
        async with async_playwright() as p:
            async with acquire_page(p, cfg, patchright_active) as (page, mode):
                logger.debug(f"Ghost browsing {url} via mode={mode}")
                html = await render_page(page, url, cfg)
                usage = dict(empty_usage)
                if cfg.navigate and cfg.nav_instruction:
                    # usage normalized to {"input", "output", "total"}; the
                    # returned page may differ if a new tab was followed.
                    usage, page = await _run_agentic_navigation(page, cfg, url)
                    logger.info(f"Ghost navigation token usage: {usage}")
                    html = await page.content()
                return html, usage

    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run())
    except Exception as e:
        logger.debug(f"Ghost browsing failed for {url}: {e}")
        return None, empty_usage
