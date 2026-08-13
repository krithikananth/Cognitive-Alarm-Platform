const { test, expect } = require('@playwright/test');
const { ACCOUNTS } = require('../helpers/accounts');
const { login } = require('../helpers/app');

const admin = ACCOUNTS.admin;
// Owned by this journey alone, so deactivating it cannot disturb other specs.
const target = ACCOUNTS.unverified;

/**
 * The user-management card.
 *
 * The admin page also renders system-report tables, so page-wide row and cell
 * lookups would match more than one listing.
 */
function usersPanel(page) {
    return page
        .locator('.card')
        .filter({ has: page.getByRole('heading', { name: /All Users/ }) });
}

test.describe('Journey: administrator manages the platform', () => {
    test('an admin lands on the admin panel and sees live platform data', async ({ page }) => {
        await login(page, admin);
        await expect(page).toHaveURL(/\/admin$/);
        await expect(page.getByRole('heading', { name: 'Admin Dashboard' })).toBeVisible();

        // Roster of every seeded account is loaded from the admin APIs.
        const users = usersPanel(page);
        await expect(users.getByRole('heading', { name: /All Users/ })).toBeVisible();
        await expect(users.getByRole('cell', { name: admin.email })).toBeVisible();
        await expect(users.getByRole('cell', { name: ACCOUNTS.user.email })).toBeVisible();

        // Response times are measured from the traffic this very run generated.
        await expect(page.getByRole('heading', { name: 'API Performance' })).toBeVisible();
        await expect(page.getByText('Slowest routes by p95')).toBeVisible();
    });

    test('an admin finds a user by search, deactivates them and restores them', async ({
        browser,
        page,
    }) => {
        await login(page, admin);
        await expect(page).toHaveURL(/\/admin$/);

        // ── 1. Search narrows the table to the target account ──
        const users = usersPanel(page);
        await users.getByPlaceholder('Search users…').fill(target.username);
        const row = users.getByRole('row').filter({ hasText: target.email });
        await expect(row).toBeVisible();
        await expect(row.getByText('Active')).toBeVisible();

        // ── 2. Deactivating goes through an explicit confirmation ──
        await row.getByLabel(`Deactivate ${target.username}`).click();
        await expect(
            page.getByRole('heading', { name: `Deactivate ${target.username}?` })
        ).toBeVisible();
        await page.getByRole('button', { name: 'Deactivate', exact: true }).click();

        await expect(row.getByText('Inactive')).toBeVisible();

        // ── 3. The change is server-side, so it survives a reload ──
        await page.reload();
        await usersPanel(page).getByPlaceholder('Search users…').fill(target.username);
        const reloadedRow = usersPanel(page).getByRole('row').filter({ hasText: target.email });
        await expect(reloadedRow.getByText('Inactive')).toBeVisible();

        // ── 4. A deactivated account really cannot sign in ──
        // A separate context, so the admin's own session cookie is not reused —
        // otherwise /login would just redirect straight back to the admin panel.
        const guest = await browser.newContext({ baseURL: new URL(page.url()).origin });
        const other = await guest.newPage();
        await other.goto('/login');
        await other.locator('#login-email').fill(target.email);
        await other.locator('#login-password').fill(target.password);
        await other.locator('#login-submit').click();
        await expect(other.getByText(/deactivated|inactive|disabled/i).first()).toBeVisible();
        await expect(other).toHaveURL(/\/login$/);
        await guest.close();

        // ── 5. Restore the account so the suite is repeatable ──
        await reloadedRow.getByLabel(`Activate ${target.username}`).click();
        await expect(reloadedRow.getByText('Active')).toBeVisible();
    });

    test('an admin can open a user record for editing', async ({ page }) => {
        await login(page, admin);
        await usersPanel(page).getByPlaceholder('Search users…').fill(ACCOUNTS.user.username);
        const row = usersPanel(page).getByRole('row').filter({ hasText: ACCOUNTS.user.email });
        await row.getByLabel(`Edit ${ACCOUNTS.user.username}`).click();

        const modal = page.getByRole('heading', { name: 'Edit user' });
        await expect(modal).toBeVisible();
        await expect(page.getByPlaceholder('user@example.com')).toHaveValue(ACCOUNTS.user.email);

        await page.getByLabel('Close').click();
        await expect(modal).toHaveCount(0);
    });
});
