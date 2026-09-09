"""UI-only adapter: no target business API, DOM mutations or JS task execution."""
from typing import Protocol
from decimal import Decimal, InvalidOperation
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from .models import Target, Step
from .policy import Policy, PolicyError


class SurfaceError(Exception):
    pass


class Surface(Protocol):
    def observe(self) -> dict: ...
    def act(self, step: Step, inputs: dict): ...
    def visible(self, target: Target) -> bool: ...
    def open(self, path: str): ...


class BrowserSurface:
    def __init__(self, policy: Policy, headed=False):
        self.policy = policy
        self.headed = headed
        self.owner = "automation"
        self.violation = False
        self.dialog = False
        self.human_events = []

    def __enter__(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=not self.headed)
        self.context = self.browser.new_context(service_workers="block", accept_downloads=False)
        self.context.route("**/*", self._route)
        self.context.route_web_socket("**/*", lambda ws: ws.close())
        self.context.on("page", self._new_page)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.policy.wait_ms)
        return self

    def __exit__(self, *_):
        self.context.close()
        self.browser.close()
        self.pw.stop()

    def _new_page(self, page):
        page.on("dialog", self._dialog)
        page.on("download", lambda d: d.cancel())
        if hasattr(self, "page"):
            self.violation = True
            page.close()

    def _dialog(self, dialog):
        self.dialog = True
        dialog.dismiss()  # Never auto-accept an unknown confirmation.

    def _route(self, route):
        try:
            self.policy.check_url(route.request.url)
            if route.request.method != "GET":
                raise PolicyError("method_not_allowed")
            route.continue_()
        except PolicyError:
            self.violation = True
            route.abort()

    def check(self):
        if self.violation:
            raise PolicyError("blocked_network_or_popup")
        if self.dialog:
            raise SurfaceError("unexpected_dialog")
        self.policy.check_url(self.page.url)

    def open(self, path):
        url = self.policy.origin + path
        self.policy.check_url(url)
        self.page.goto(url, wait_until="domcontentloaded")
        self.check()

    def locator(self, target):
        root = self.page.frame_locator(f'iframe[title="{target.frame}"]') if target.frame else self.page
        if target.strategy == "role":
            return root.get_by_role(target.role, name=target.name, exact=True)
        if target.strategy == "label":
            return root.get_by_label(target.name, exact=True)
        return root.get_by_text(target.name, exact=True).filter(visible=True)

    def visible(self, target):
        loc = self.locator(target)
        return loc.count() == 1 and loc.is_visible()

    def observe(self):
        self.check()
        # A value-free structural snapshot. Only reviewed control labels reach the model/logs.
        controls = []
        for c in self.policy.controls:
            loc = self.locator(c.target)
            count = loc.count()
            controls.append({"target": c.target.model_dump(), "matches": count,
                             "visible": count == 1 and loc.is_visible(),
                             "enabled": count == 1 and loc.is_enabled()})
        return {"controls": controls,
                "conditions": [c.code for c in self.policy.conditions if self.visible(c.target)]}

    def act(self, step, inputs):
        if self.owner != "automation":
            raise SurfaceError("human_owns_session")
        self.check()
        self.policy.check_step(step)
        loc = self.locator(step.target)
        try:
            if loc.count() > 1:
                raise SurfaceError("ambiguous_control")
            loc.wait_for(state="visible")
            if loc.count() != 1:
                raise SurfaceError("ambiguous_control")
            result = None
            if step.action == "click":
                loc.click()
            elif step.action == "fill":
                loc.fill(str(inputs[step.input_ref]))
            elif step.action == "read":
                text = loc.inner_text().strip()
                kind = self.policy.outputs[step.output_ref].type
                if kind == "decimal":
                    result = format(Decimal(text.replace("$", "").replace(",", "")), ".2f")
                    if not Decimal(result).is_finite():
                        raise ValueError()
                elif kind == "integer":
                    result = int(text)
                else:
                    result = text
            self.check()
            return result
        except PlaywrightTimeout:
            raise SurfaceError("control_timeout") from None
        except (ValueError, InvalidOperation):
            raise SurfaceError("output_type_mismatch") from None

    def start_human_capture(self):
        self.owner = "human"
        self.human_events.clear()
        # Capture event kind + index in reviewed catalog, never typed values or raw labels.
        labels = [c.target.name for c in self.policy.controls]
        if not hasattr(self, "capture_installed"):
            self.page.expose_binding("__handsHumanEvent", self._capture_event)
        self.capture_installed = True
        for frame in self.page.frames:
            frame.evaluate("""labels => {
              window.__handsCapture = true;
              if (window.__handsListeners) return;
              window.__handsListeners = true;
              for (const kind of ['click','input']) document.addEventListener(kind, e => {
                if (!window.__handsCapture) return;
                const el = e.target;
                const name = el.getAttribute('aria-label') || el.labels?.[0]?.textContent || el.textContent;
                const index = labels.indexOf((name || '').trim());
                window.__handsHumanEvent({action:kind, control:index});
              }, true);
            }""", labels)

    def _capture_event(self, source, event):
        # The page is untrusted, including callbacks it invokes itself.
        if self.owner != "human" or not isinstance(event, dict):
            return
        action, control = event.get("action"), event.get("control")
        if action not in ("click", "input") or type(control) is not int:
            return
        if not -1 <= control < len(self.policy.controls):
            return
        self.human_events.append({"action": action, "control": control})

    def stop_human_capture(self):
        for frame in self.page.frames:
            frame.evaluate("window.__handsCapture = false")
        self.owner = "automation"
        self.dialog = False
