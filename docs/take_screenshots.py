"""Take screenshots of the app for README documentation."""
import asyncio
from playwright.async_api import async_playwright

BASE = "http://localhost"
ADMIN_USER = "raafael.keikko@gmail.com"
ADMIN_PASS = "02Enmui1ta"
OUT = "docs/screenshots"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # 1. Login page
        await page.goto(f"{BASE}/login")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/01_login.png", full_page=False)
        print("✓ Login page")

        # 2. Admin login
        await page.goto(f"{BASE}/admin/login")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/06_admin_login.png", full_page=False)
        print("✓ Admin login page")

        # Admin login and navigate
        await page.fill('input[type="text"], input[name="username"], input[placeholder*="user" i], input[placeholder*="email" i]', ADMIN_USER)
        await page.fill('input[type="password"]', ADMIN_PASS)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        # 3. Admin users page
        await page.screenshot(path=f"{OUT}/07_admin_users.png", full_page=False)
        print("✓ Admin users page")

        # 4. Admin settings
        await page.goto(f"{BASE}/admin/settings")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=f"{OUT}/08_admin_settings.png", full_page=True)
        print("✓ Admin settings page")

        # Now register a test user & login as regular user
        await page.goto(f"{BASE}/login")
        await page.wait_for_timeout(1000)

        # Try to find register link/tab
        register_link = page.locator('text=Register, a:has-text("Register"), button:has-text("Register")')
        if await register_link.count() > 0:
            await register_link.first.click()
            await page.wait_for_timeout(1000)
            await page.screenshot(path=f"{OUT}/02_register.png", full_page=False)
            print("✓ Register page")

        # Login as admin to get screenshots of user pages
        # Use admin token to create dummy data views
        await page.goto(f"{BASE}/admin/login")
        await page.wait_for_timeout(1000)
        await page.fill('input[type="text"], input[name="username"], input[placeholder*="user" i], input[placeholder*="email" i]', ADMIN_USER)
        await page.fill('input[type="password"]', ADMIN_PASS)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        # Take screenshots of main navigation pages (these show the layout even without user data)
        # Dashboard
        await page.goto(f"{BASE}/")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/03_dashboard.png", full_page=False)
        print("✓ Dashboard")

        # Prompts page
        await page.goto(f"{BASE}/prompts")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/04_prompts.png", full_page=False)
        print("✓ Prompts page")

        # Channels page
        await page.goto(f"{BASE}/channels")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/05_channels.png", full_page=False)
        print("✓ Channels page")

        # Summary page
        await page.goto(f"{BASE}/summary")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/09_summary.png", full_page=False)
        print("✓ Summary page")

        # Settings page
        await page.goto(f"{BASE}/settings")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/10_settings.png", full_page=False)
        print("✓ Settings page")

        # Bots page
        await page.goto(f"{BASE}/bots")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/11_bots.png", full_page=False)
        print("✓ Bots page")

        await browser.close()
        print("\nAll screenshots saved to docs/screenshots/")


asyncio.run(main())
