const { test, expect } = require('@playwright/test');
const { ACCOUNTS } = require('../helpers/accounts');
const { waitForLink, toRelative } = require('../helpers/mailbox');
const { login, logout } = require('../helpers/app');

const account = ACCOUNTS.resetter;

test.describe('Journey: forgotten password → emailed reset link → sign in again', () => {
    test('a locked-out user resets their password and the old one stops working', async ({
        page,
    }) => {
        // ── 1. Reach the reset request from the login page, as a user would ──
        await page.goto('/login');
        await page.getByRole('link', { name: 'Forgot password?' }).click();
        await page.waitForURL(/\/forgot-password$/);

        await page.locator('#forgot-email').fill(account.email);
        await page.locator('#forgot-submit').click();

        // The response is deliberately generic so it cannot enumerate accounts.
        await expect(page.getByText(/If an account exists|check your inbox/i).first()).toBeVisible();

        // ── 2. Follow the link the backend actually mailed ──
        const link = await waitForLink('reset-password', account.email);
        await page.goto(toRelative(link.url));
        await expect(page.getByRole('heading', { name: 'Reset Password' })).toBeVisible();

        await page.locator('#reset-password').fill(account.newPassword);
        await page.locator('#reset-password-confirm').fill(account.newPassword);
        await page.locator('#reset-submit').click();

        // ── 3. The reset returns the user to the login page ──
        await page.waitForURL(/\/login$/);

        // ── 4. The superseded password is rejected ──
        await page.locator('#login-email').fill(account.email);
        await page.locator('#login-password').fill(account.password);
        await page.locator('#login-submit').click();
        await expect(page.getByText(/Invalid email or password/i).first()).toBeVisible();
        await expect(page).toHaveURL(/\/login$/);

        // ── 5. The new password signs in and reaches the dashboard ──
        await login(page, account, { password: account.newPassword });
        await expect(page).toHaveURL(/\/dashboard$/);
        await expect(page.getByText(account.email).first()).toBeVisible();

        await logout(page);
        await expect(page).toHaveURL(/\/login$/);
    });

    test('a reset page opened without a token refuses to change anything', async ({ page }) => {
        await page.goto('/reset-password');
        await expect(page.locator('#reset-submit')).toHaveCount(0);
        await page.getByRole('link', { name: 'Request Reset Link' }).click();
        await page.waitForURL(/\/forgot-password$/);
        await expect(page.locator('#forgot-submit')).toBeVisible();
    });
});
