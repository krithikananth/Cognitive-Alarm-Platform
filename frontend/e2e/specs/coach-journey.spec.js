const { test, expect } = require('@playwright/test');
const { ACCOUNTS } = require('../helpers/accounts');
const { login, logout } = require('../helpers/app');

const coach = ACCOUNTS.coach;
const client = ACCOUNTS.user;

test.describe('Journey: wellness coach reviews an assigned client', () => {
    test('a coach lands on their own workspace, opens a client and reads their analytics', async ({
        page,
    }) => {
        // ── 1. Login sends a coach to the coach workspace, not the user dashboard ──
        await login(page, coach);
        await expect(page).toHaveURL(/\/wellness$/);
        await expect(
            page.getByRole('heading', { name: 'Wellness Coach Dashboard' })
        ).toBeVisible();
        await expect(page.getByText(coach.email).first()).toBeVisible();

        // ── 2. The assigned client is on the roster ──
        const roster = page.locator('#coach-clients');
        await expect(roster.getByRole('heading', { name: /My Clients/ })).toBeVisible();
        const clientRow = roster.getByRole('button').filter({ hasText: client.email });
        await expect(clientRow).toBeVisible();

        // ── 3. Search narrows the roster, and clearing it brings the client back ──
        const search = page.getByPlaceholder('Search clients');
        await search.fill('nobody-matches-this');
        await expect(page.getByText('No clients match these filters')).toBeVisible();
        await search.fill(client.fullName.split(' ')[0]);
        await expect(roster.getByRole('button').filter({ hasText: client.email })).toBeVisible();

        // ── 4. Selecting the client opens their detail panels ──
        await roster.getByRole('button').filter({ hasText: client.email }).click();
        await expect(page.getByRole('heading', { name: client.fullName })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Profile Information' })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Core Metrics' })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Behaviour Insights' })).toBeVisible();
        await expect(page.getByRole('heading', { name: 'Habit Insights' })).toBeVisible();
    });

    test('a coach cannot cross into the admin area', async ({ page }) => {
        await login(page, coach);
        await expect(page).toHaveURL(/\/wellness$/);

        // Even by URL, the admin route is refused.
        await page.goto('/admin');
        await expect(page).toHaveURL(/\/access-denied$/);
        await expect(page.getByText(/Access Denied/i).first()).toBeVisible();

        // The generic dashboard route routes a coach back to their workspace.
        await page.goto('/dashboard');
        await expect(page).toHaveURL(/\/wellness$/);

        await logout(page);
        // The session is really gone: a protected page bounces back to login.
        await page.goto('/wellness');
        await expect(page).toHaveURL(/\/login$/);
    });
});
