"""Dr. Flash — Browser Automation Tool.

Uses Playwright for reliable browser control. Dr. Flash can:
- Navigate to URLs and extract page content
- Search the web and return results
- Fill forms and interact with pages
- Extract specific information from web pages

All browsing happens locally. The LLM (Ollama) processes the content
locally. No personal data is sent to any AI cloud.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import (
    CapabilityToken, ToolCall, ToolCapability, ToolRegistration, ToolResult,
)
from services.execution_broker import ToolAdapter


class BrowserTool(ToolAdapter):
    """Browse the web, search, extract content via Playwright."""

    def __init__(self) -> None:
        self._browser = None
        self._context = None

    @property
    def tool_id(self) -> str:
        return "browser"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="browser",
            version="0.1.0",
            description="Browse the web: navigate pages, search, extract text, fill forms.",
            capabilities=[
                ToolCapability(
                    action="navigate",
                    resource_scope="web",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Navigate to a URL and extract the page text content. Args: url.",
                ),
                ToolCapability(
                    action="search",
                    resource_scope="web",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Search the web using DuckDuckGo and return result snippets. Args: query.",
                ),
                ToolCapability(
                    action="extract",
                    resource_scope="web",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Extract specific info from the current page. Args: url, selector (CSS, optional).",
                ),
                ToolCapability(
                    action="screenshot",
                    resource_scope="web",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Take a screenshot of a web page. Args: url.",
                ),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=30,
        )

    async def _get_browser(self):
        """Lazy-init Playwright browser."""
        if self._browser is None:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent="Dr.Flash/1.0 (Personal AI Assistant)"
            )
        return self._context

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            if call.action == "navigate":
                return await self._navigate(call)
            elif call.action == "search":
                return await self._search(call)
            elif call.action == "extract":
                return await self._extract(call)
            elif call.action == "screenshot":
                return await self._screenshot(call)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown: {call.action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e)[:300])

    async def observe(self, scope: str) -> dict:
        return {"type": "browser"}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}

    async def _navigate(self, call: ToolCall) -> ToolResult:
        url = call.args.get("url", "")
        if not url:
            return ToolResult(call_id=call.call_id, success=False, error="url required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        ctx = await self._get_browser()
        page = await ctx.new_page()
        try:
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            title = await page.title()
            # Extract main text content
            text = await page.evaluate("""
                () => {
                    const el = document.querySelector('main') || document.querySelector('article') || document.body;
                    return el ? el.innerText.substring(0, 5000) : '';
                }
            """)
            url_final = page.url
            return ToolResult(call_id=call.call_id, success=True, data={
                "url": url_final, "title": title,
                "text": text[:5000], "text_length": len(text),
            })
        finally:
            await page.close()

    async def _search(self, call: ToolCall) -> ToolResult:
        query = call.args.get("query", "")
        if not query:
            return ToolResult(call_id=call.call_id, success=False, error="query required")

        import urllib.parse
        search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"

        ctx = await self._get_browser()
        page = await ctx.new_page()
        try:
            await page.goto(search_url, timeout=20000, wait_until="domcontentloaded")

            results = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.result');
                    return Array.from(items).slice(0, 8).map(el => {
                        const title = el.querySelector('.result__title')?.innerText || '';
                        const snippet = el.querySelector('.result__snippet')?.innerText || '';
                        const url = el.querySelector('.result__url')?.innerText || '';
                        return { title, snippet, url };
                    });
                }
            """)

            return ToolResult(call_id=call.call_id, success=True, data={
                "query": query,
                "results": results,
                "count": len(results),
            })
        finally:
            await page.close()

    async def _extract(self, call: ToolCall) -> ToolResult:
        url = call.args.get("url", "")
        selector = call.args.get("selector", "")
        if not url:
            return ToolResult(call_id=call.call_id, success=False, error="url required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        ctx = await self._get_browser()
        page = await ctx.new_page()
        try:
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")

            if selector:
                elements = await page.query_selector_all(selector)
                texts = []
                for el in elements[:20]:
                    t = await el.inner_text()
                    if t.strip():
                        texts.append(t.strip()[:500])
                return ToolResult(call_id=call.call_id, success=True, data={
                    "url": url, "selector": selector,
                    "elements": texts, "count": len(texts),
                })
            else:
                # Extract all headings and paragraphs
                content = await page.evaluate("""
                    () => {
                        const items = [];
                        document.querySelectorAll('h1,h2,h3,p,li').forEach(el => {
                            const text = el.innerText.trim();
                            if (text) items.push({ tag: el.tagName, text: text.substring(0, 300) });
                        });
                        return items.slice(0, 50);
                    }
                """)
                return ToolResult(call_id=call.call_id, success=True, data={
                    "url": url, "content": content, "count": len(content),
                })
        finally:
            await page.close()

    async def _screenshot(self, call: ToolCall) -> ToolResult:
        url = call.args.get("url", "")
        if not url:
            return ToolResult(call_id=call.call_id, success=False, error="url required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        from pathlib import Path
        screenshots_dir = Path("data/screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        ctx = await self._get_browser()
        page = await ctx.new_page()
        try:
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            title = await page.title()
            filename = f"browser_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = screenshots_dir / filename
            await page.screenshot(path=str(filepath), full_page=False)
            return ToolResult(call_id=call.call_id, success=True, data={
                "url": url, "title": title,
                "screenshot": str(filepath),
            })
        finally:
            await page.close()
