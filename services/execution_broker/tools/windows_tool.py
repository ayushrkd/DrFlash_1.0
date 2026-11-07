"""Dr. Flash — Windows Automation Tool (pywinauto).

Read and control Windows applications via UI Automation.
- List open windows
- Read text from any window
- Focus/activate windows
- Click elements, type text (with policy checks)

All actions go through the execution broker's policy engine.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from services.contracts.enums import Risk, SideEffect
from services.contracts.models import (
    CapabilityToken, ToolCall, ToolCapability, ToolRegistration, ToolResult,
)
from services.execution_broker import ToolAdapter


class WindowsTool(ToolAdapter):
    """Control Windows applications via pywinauto UI Automation."""

    @property
    def tool_id(self) -> str:
        return "windows"

    @property
    def registration(self) -> ToolRegistration:
        return ToolRegistration(
            tool_id="windows",
            version="0.1.0",
            description="Read and control Windows applications: list windows, read text, click, type.",
            capabilities=[
                ToolCapability(
                    action="list_windows",
                    resource_scope="windows",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="List all visible open windows with their titles and process names.",
                ),
                ToolCapability(
                    action="get_active_window",
                    resource_scope="windows",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Get info about the currently active/foreground window.",
                ),
                ToolCapability(
                    action="read_window_text",
                    resource_scope="windows",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="Read all text content from a window by title (partial match). Args: title.",
                ),
                ToolCapability(
                    action="focus_window",
                    resource_scope="windows",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Bring a window to the front. Args: title (partial match).",
                ),
                ToolCapability(
                    action="list_controls",
                    resource_scope="windows",
                    side_effect=SideEffect.READ,
                    risk=Risk.R0_READ,
                    description="List UI controls (buttons, text fields, etc.) in a window. Args: title.",
                ),
                ToolCapability(
                    action="click_button",
                    resource_scope="windows",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Click a button in a window. Args: title (window), button_name.",
                ),
                ToolCapability(
                    action="type_text",
                    resource_scope="windows",
                    side_effect=SideEffect.LOCAL_WRITE,
                    risk=Risk.R1_LOCAL_WRITE,
                    description="Type text into the focused control of a window. Args: title, text.",
                ),
            ],
            requires_approval_above=Risk.R2_EXTERNAL_WRITE,
            execution_timeout_seconds=15,
        )

    async def execute(self, call: ToolCall, token: CapabilityToken) -> ToolResult:
        try:
            action = call.action
            if action == "list_windows":
                return await self._list_windows(call)
            elif action == "get_active_window":
                return await self._get_active_window(call)
            elif action == "read_window_text":
                return await self._read_window_text(call)
            elif action == "focus_window":
                return await self._focus_window(call)
            elif action == "list_controls":
                return await self._list_controls(call)
            elif action == "click_button":
                return await self._click_button(call)
            elif action == "type_text":
                return await self._type_text(call)
            return ToolResult(call_id=call.call_id, success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e)[:300])

    async def observe(self, scope: str) -> dict:
        return {"type": "windows", "timestamp": datetime.now(timezone.utc).isoformat()}

    async def health(self) -> dict:
        return {"tool_id": self.tool_id, "status": "healthy"}

    async def _list_windows(self, call: ToolCall) -> ToolResult:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        windows = []
        for win in desktop.windows():
            try:
                title = win.window_text()
                if not title or title.strip() == "":
                    continue
                windows.append({
                    "title": title,
                    "class_name": win.class_name(),
                    "visible": win.is_visible(),
                    "enabled": win.is_enabled(),
                    "rect": {
                        "left": win.rectangle().left,
                        "top": win.rectangle().top,
                        "right": win.rectangle().right,
                        "bottom": win.rectangle().bottom,
                    },
                })
            except Exception:
                continue
        return ToolResult(call_id=call.call_id, success=True,
                          data={"windows": windows[:30], "count": len(windows)})

    async def _get_active_window(self, call: ToolCall) -> ToolResult:
        import ctypes
        from pywinauto import Desktop

        # Get foreground window handle
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        desktop = Desktop(backend="uia")

        for win in desktop.windows():
            try:
                if win.handle == hwnd:
                    return ToolResult(call_id=call.call_id, success=True, data={
                        "title": win.window_text(),
                        "class_name": win.class_name(),
                        "handle": hwnd,
                        "rect": {
                            "left": win.rectangle().left,
                            "top": win.rectangle().top,
                            "width": win.rectangle().width(),
                            "height": win.rectangle().height(),
                        },
                    })
            except Exception:
                continue
        return ToolResult(call_id=call.call_id, success=True,
                          data={"title": "Unknown", "handle": hwnd})

    def _find_window(self, title: str):
        """Find a window by partial title match."""
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        title_lower = title.lower()
        for win in desktop.windows():
            try:
                wt = win.window_text()
                if wt and title_lower in wt.lower():
                    return win
            except Exception:
                continue
        return None

    async def _read_window_text(self, call: ToolCall) -> ToolResult:
        title = call.args.get("title", "")
        if not title:
            return ToolResult(call_id=call.call_id, success=False, error="title required")

        win = self._find_window(title)
        if not win:
            return ToolResult(call_id=call.call_id, success=False,
                              error=f"No window matching '{title}'")

        try:
            texts = []
            for child in win.descendants():
                try:
                    t = child.window_text()
                    if t and t.strip():
                        ctrl_type = child.friendly_class_name()
                        texts.append({"type": ctrl_type, "text": t[:200]})
                except Exception:
                    continue

            return ToolResult(call_id=call.call_id, success=True, data={
                "window": win.window_text(),
                "elements": texts[:50],
                "element_count": len(texts),
            })
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e)[:200])

    async def _focus_window(self, call: ToolCall) -> ToolResult:
        title = call.args.get("title", "")
        if not title:
            return ToolResult(call_id=call.call_id, success=False, error="title required")

        win = self._find_window(title)
        if not win:
            return ToolResult(call_id=call.call_id, success=False,
                              error=f"No window matching '{title}'")
        try:
            win.set_focus()
            return ToolResult(call_id=call.call_id, success=True,
                              data={"focused": win.window_text()})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e)[:200])

    async def _list_controls(self, call: ToolCall) -> ToolResult:
        title = call.args.get("title", "")
        if not title:
            return ToolResult(call_id=call.call_id, success=False, error="title required")

        win = self._find_window(title)
        if not win:
            return ToolResult(call_id=call.call_id, success=False,
                              error=f"No window matching '{title}'")

        controls = []
        for child in win.descendants():
            try:
                ctrl_type = child.friendly_class_name()
                name = child.window_text()
                if ctrl_type in ("Button", "Edit", "ComboBox", "CheckBox",
                                 "RadioButton", "MenuItem", "TabItem", "ListItem"):
                    controls.append({
                        "type": ctrl_type,
                        "name": name[:100] if name else "",
                        "enabled": child.is_enabled(),
                    })
            except Exception:
                continue

        return ToolResult(call_id=call.call_id, success=True, data={
            "window": win.window_text(),
            "controls": controls[:40],
            "count": len(controls),
        })

    async def _click_button(self, call: ToolCall) -> ToolResult:
        title = call.args.get("title", "")
        button_name = call.args.get("button_name", "")
        if not title or not button_name:
            return ToolResult(call_id=call.call_id, success=False,
                              error="title and button_name required")

        win = self._find_window(title)
        if not win:
            return ToolResult(call_id=call.call_id, success=False,
                              error=f"No window matching '{title}'")

        try:
            btn_lower = button_name.lower()
            for child in win.descendants():
                try:
                    if (child.friendly_class_name() == "Button" and
                            btn_lower in child.window_text().lower()):
                        child.click()
                        return ToolResult(call_id=call.call_id, success=True,
                                          data={"clicked": child.window_text()})
                except Exception:
                    continue
            return ToolResult(call_id=call.call_id, success=False,
                              error=f"Button '{button_name}' not found in '{title}'")
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e)[:200])

    async def _type_text(self, call: ToolCall) -> ToolResult:
        title = call.args.get("title", "")
        text = call.args.get("text", "")
        if not title or not text:
            return ToolResult(call_id=call.call_id, success=False,
                              error="title and text required")

        win = self._find_window(title)
        if not win:
            return ToolResult(call_id=call.call_id, success=False,
                              error=f"No window matching '{title}'")

        try:
            win.set_focus()
            win.type_keys(text[:500], with_spaces=True)
            return ToolResult(call_id=call.call_id, success=True,
                              data={"typed": text[:100], "window": win.window_text()})
        except Exception as e:
            return ToolResult(call_id=call.call_id, success=False, error=str(e)[:200])
