"""One Playwright driver and one Chromium for the whole run; every browser test gets a fresh context.

A new driver plus browser per test cost about 1.1 s, a new context about 0.26 s. A context has its own
cookies, storage, init scripts and permissions, so tests stay isolated. If a test crashed the shared browser,
the next test relaunches it."""
import pytest


class _SharedBrowser:
    def __init__(self):
        self.pw = None
        self.browser = None

    def get(self):
        from playwright.sync_api import sync_playwright
        from test_app import CHROME
        if self.browser is not None and self.browser.is_connected():
            return self.browser
        if self.pw is None:
            self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        return self.browser

    def close(self):
        try:
            if self.browser is not None and self.browser.is_connected():
                self.browser.close()
        finally:
            if self.pw is not None:
                self.pw.stop()
            self.pw = self.browser = None


@pytest.fixture(scope="session")
def _shared_browser():
    shared = _SharedBrowser()
    yield shared
    shared.close()


@pytest.fixture
def new_context(_shared_browser):
    """Make a fresh browser context in the shared Chromium; it is closed when the test ends."""
    from test_app import CHROME
    if not CHROME:
        pytest.skip("Chromium not available")
    made = []

    def make(**kwargs):
        ctx = _shared_browser.get().new_context(**kwargs)
        made.append(ctx)
        return ctx

    yield make
    for ctx in made:
        try:
            ctx.close()
        except Exception:
            pass  # the browser already went away
