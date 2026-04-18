"""Take screenshots of the app for README documentation.

Uses a real user account for user-facing pages and admin credentials
for admin pages. Email addresses are masked in all screenshots.
"""
import asyncio
from playwright.async_api import async_playwright

BASE = "http://localhost"
# Regular user credentials
USER_EMAIL = "raafael.keikko@gmail.com"
USER_PASS = "enmuista"
# Admin credentials (from .env)
ADMIN_USER = "raafael.keikko@gmail.com"
ADMIN_PASS = "02Enmui1ta"
OUT = "docs/screenshots"

# JS snippet to mask any visible email addresses on the page
MASK_EMAIL_JS = """
() => {
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walk.nextNode()) {
        const node = walk.currentNode;
        node.textContent = node.textContent.replace(
            /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/g,
            'user@example.com'
        );
    }
    // Also mask input values
    document.querySelectorAll('input').forEach(el => {
        if (el.value && el.value.includes('@')) {
            el.value = 'user@example.com';
        }
    });
}
"""


async def screenshot(page, path, full=False):
    """Mask emails then take screenshot."""
    await page.evaluate(MASK_EMAIL_JS)
    await page.screenshot(path=path, full_page=full)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})

        # ── 1. Login page (empty form) ────────────────────
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/01_login.png")
        print("✓ Login page")

        # ── 2. Login as regular user ──────────────────────
        await page.fill('input[placeholder="Email"]', USER_EMAIL)
        await page.fill('input[type="password"]', USER_PASS)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2500)

        # ── 3. Dashboard ─────────────────────────────────
        await page.goto(f"{BASE}/")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/03_dashboard.png")
        print("✓ Dashboard")

        # ── 4. Prompts page ──────────────────────────────
        await page.goto(f"{BASE}/prompts")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/04_prompts.png")
        print("✓ Prompts page")

        # ── 5. Channels page ─────────────────────────────
        await page.goto(f"{BASE}/channels")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/05_channels.png")
        print("✓ Channels page")

        # ── 6. Summary page ──────────────────────────────
        await page.goto(f"{BASE}/summary")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/09_summary.png")
        print("✓ Summary page")

        # ── 7. Settings page ─────────────────────────────
        await page.goto(f"{BASE}/settings")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/10_settings.png")
        print("✓ Settings page")

        # ── 8. Bots page ─────────────────────────────────
        await page.goto(f"{BASE}/bots")
        await page.wait_for_timeout(1500)
        await screenshot(page, f"{OUT}/11_bots.png")
        print("✓ Bots page")

        await page.close()
        await ctx.close()

        # ── ADMIN PAGES (separate browser context) ───────
        ctx2 = await browser.new_context(viewport={"width": 1280, "height": 800})
        page2 = await ctx2.new_page()

        # 9. Admin login page (empty)
        await page2.goto(f"{BASE}/admin/login")
        await page2.wait_for_timeout(1500)
        await screenshot(page2, f"{OUT}/06_admin_login.png")
        print("✓ Admin login page")

        # Login as admin
        await page2.fill('input[placeholder="Admin username"]', ADMIN_USER)
        await page2.fill('input[type="password"]', ADMIN_PASS)
        await page2.click('button[type="submit"]')
        await page2.wait_for_timeout(3000)

        # 10. Admin users page — wait for table/content to load
        await page2.goto(f"{BASE}/admin/users")
        await page2.wait_for_timeout(3000)
        await screenshot(page2, f"{OUT}/07_admin_users.png")
        print("✓ Admin users page")

        # 11. Admin settings page
        await page2.goto(f"{BASE}/admin/settings")
        await page2.wait_for_timeout(3000)
        await screenshot(page2, f"{OUT}/08_admin_settings.png", full=True)
        print("✓ Admin settings page")

        await browser.close()
        print(f"\nAll screenshots saved to {OUT}/")


asyncio.run(main())
