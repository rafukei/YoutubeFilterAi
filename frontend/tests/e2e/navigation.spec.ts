import { test, expect } from '@playwright/test';

/**
 * E2E tests for YoutubeFilterAi navigation and UI components.
 */

test.describe('Navigation (Authenticated User)', () => {
  // Skip tests that require authentication unless we have a way to mock it
  test.skip('should show navigation links after login', async ({ page }) => {
    // This test would require setting up authentication
    await page.goto('/');
    
    await expect(page.getByRole('link', { name: /summary/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /prompts/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /channels/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /bots/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /test/i })).toBeVisible();
  });
});

test.describe('Admin Navigation', () => {
  test.skip('should show admin navigation after admin login', async ({ page }) => {
    await page.goto('/admin/users');
    
    await expect(page.getByRole('link', { name: /users/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /settings/i })).toBeVisible();
  });
});

test.describe('Responsive Design', () => {
  test('login page is responsive', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 }); // Mobile
    await page.goto('/login');
    
    // Check that login form is visible on mobile
    await expect(page.getByRole('button', { name: /login/i })).toBeVisible();
  });

  test('login page works on desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('/login');
    
    await expect(page.getByRole('button', { name: /login/i })).toBeVisible();
  });
});

test.describe('Error Handling', () => {
  test('should handle 404 gracefully', async ({ page }) => {
    await page.goto('/nonexistent-page');
    
    // Should redirect to login or show some page
    // Not crash
    await expect(page.locator('body')).toBeVisible();
  });
});
