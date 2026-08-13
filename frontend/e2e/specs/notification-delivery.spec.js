const { test, expect } = require('@playwright/test');
const { ACCOUNTS } = require('../helpers/accounts');
const { login, navigateTo } = require('../helpers/app');

const account = ACCOUNTS.user;

async function openBell(page) {
    await page.locator('#notification-bell').click();
    await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
}

test.describe('Journey: notification delivery to the in-app inbox', () => {
    test('a delivered notification reaches the bell, survives a reload and can be read', async ({
        page,
    }) => {
        await login(page, account);
        await expect(page.locator('#notification-bell')).toBeVisible();

        // ── 1. Open the inbox and ask the backend to deliver one ──
        await openBell(page);
        await page.getByTitle('Send test notification').click();

        // The toast carries the id the server assigned, so this is a real delivery.
        await expect(page.getByText(/Test notification sent! \(ID: \d+\)/)).toBeVisible();

        // ── 2. It is listed as unread ──
        const row = page.getByText(/Test Notification/).first();
        await expect(row).toBeVisible();
        await expect(page.getByText(/\d+ unread/)).toBeVisible();

        // ── 3. Reading it is persisted, not just local UI state ──
        await page.getByRole('button', { name: 'Mark all read' }).click();
        await expect(page.getByText('All caught up ✓')).toBeVisible();

        await page.reload();
        await openBell(page);
        await expect(page.getByText(/Test Notification/).first()).toBeVisible();
        await expect(page.getByText('All caught up ✓')).toBeVisible();
        await expect(page.getByTitle('Mark as read')).toHaveCount(0);
    });

    test('the inbox follows the user across pages', async ({ page }) => {
        await login(page, account);

        await navigateTo(page, 'Reports', '/reports');
        await openBell(page);
        await expect(page.getByText(/Test Notification/).first()).toBeVisible();

        // Clicking away closes the panel without losing the page underneath.
        await page.getByRole('heading', { name: 'Lifestyle Reports' }).click();
        await expect(page.getByRole('heading', { name: 'Notifications' })).toHaveCount(0);
        await expect(page).toHaveURL(/\/reports$/);

        await navigateTo(page, 'Dashboard', '/dashboard');
        await openBell(page);
        await expect(page.getByText(/Test Notification/).first()).toBeVisible();
    });
});
