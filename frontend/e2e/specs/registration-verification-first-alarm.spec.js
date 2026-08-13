const { test, expect } = require('@playwright/test');
const { uniqueEmail } = require('../helpers/accounts');
const { waitForLink, toRelative } = require('../helpers/mailbox');
const { login, navigateTo } = require('../helpers/app');

const PASSWORD = 'NewUser123!';

test.describe('Journey: registration → email verification → first alarm', () => {
    test('a new visitor signs up, verifies by email link and schedules their first alarm', async ({
        page,
    }) => {
        const email = uniqueEmail('signup');
        const username = `signup${Date.now()}`;

        // ── 1. Register from the public sign-up page ──
        await page.goto('/register');
        await expect(page.getByRole('heading', { name: 'Create Account' })).toBeVisible();

        await page.locator('#register-fullname').fill('Nina Newcomer');
        await page.locator('#register-username').fill(username);
        await page.locator('#register-email').fill(email);
        await page.locator('#register-password').fill(PASSWORD);
        await page.locator('#register-submit').click();

        // Registration hands the visitor to the login page.
        await page.waitForURL(/\/login$/);
        await expect(page.getByRole('heading', { name: 'Welcome Back' })).toBeVisible();

        // ── 2. Verify through the link the backend actually mailed ──
        const link = await waitForLink('verify-email', email);
        await page.goto(toRelative(link.url));

        // Scoped to the card: the toast repeats the same wording.
        await expect(
            page.locator('.card').getByText('Email verified successfully.')
        ).toBeVisible();

        // The success panel is the only way onward, so the journey stays in the UI.
        await page.getByRole('link', { name: 'Continue to Sign In' }).click();
        await page.waitForURL(/\/login$/);

        // ── 3. Sign in with the freshly verified account ──
        await login(page, { email, password: PASSWORD });
        await expect(page).toHaveURL(/\/dashboard$/);
        await expect(page.getByText(email).first()).toBeVisible();

        // ── 4. Cross into the alarm page and create the very first alarm ──
        await navigateTo(page, 'Alarms', '/alarms');
        await expect(page.getByRole('heading', { name: 'No Alarms Yet' })).toBeVisible();

        await page.locator('#create-alarm-btn').click();
        await expect(page.getByRole('heading', { name: 'Create New Alarm' })).toBeVisible();

        await page.locator('#alarm-label').fill('First Wake-up');
        await page.locator('#alarm-description').fill('Created by the end-to-end journey');

        const timeSelects = page.locator('div:has(> input#alarm-time)').locator('select');
        await timeSelects.nth(0).selectOption('6');
        await timeSelects.nth(1).selectOption('45');
        await timeSelects.nth(2).selectOption('AM');
        await expect(page.locator('#alarm-time')).toHaveValue('06:45');

        await page.locator('#alarm-submit').click();

        // ── 5. The alarm is listed, and survives a full page reload ──
        const card = page.locator('.card').filter({ hasText: 'First Wake-up' });
        await expect(card).toBeVisible();
        await expect(card.getByText('06:45')).toBeVisible();
        await expect(page.getByRole('heading', { name: 'No Alarms Yet' })).toHaveCount(0);

        await page.reload();
        await expect(
            page.locator('.card').filter({ hasText: 'First Wake-up' })
        ).toBeVisible();
        await expect(page.getByText('1 alarm configured')).toBeVisible();
    });

    test('an unverified link cannot be reused to fake a verification', async ({ page }) => {
        await page.goto('/verify-email?token=not-a-real-token');
        await expect(
            page.getByText(/Invalid or expired verification|verification token/i).first()
        ).toBeVisible();
        // The page must still offer a real way forward rather than dead-ending.
        await expect(page.locator('#verify-resend-submit')).toBeVisible();
    });
});
