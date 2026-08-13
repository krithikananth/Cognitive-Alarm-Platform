const { test, expect } = require('@playwright/test');
const { ACCOUNTS, SEEDED_ALARM_TITLE } = require('../helpers/accounts');
const { login, navigateTo } = require('../helpers/app');

const account = ACCOUNTS.user;

/** Ring the seeded alarm from its card and wait for the fullscreen modal. */
async function ring(page) {
    const card = page.locator('.card').filter({ hasText: SEEDED_ALARM_TITLE });
    await card.getByTitle('Test Ring').click();
    await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toBeVisible();
    // The challenge is fetched after the modal paints; wait for it to land.
    await expect(page.getByText(/CHALLENGE$/).first()).toBeVisible();
}

test.describe('Journey: ringing alarm → snooze escalation → failed wake', () => {
    test('snoozes are counted server-side until the limit blocks them, then the wake is abandoned', async ({
        page,
    }) => {
        await login(page, account);
        await navigateTo(page, 'Alarms', '/alarms');

        const card = page.locator('.card').filter({ hasText: SEEDED_ALARM_TITLE });
        await expect(card).toBeVisible();
        await expect(card.getByText('Snooze: 2x')).toBeVisible();

        // ── 1. First ring — snoozing is still allowed ──
        await ring(page);
        await expect(page.getByRole('button', { name: /Snooze \(0\/2 used\)/ })).toBeVisible();
        await page.getByRole('button', { name: /Snooze \(0\/2 used\)/ }).click();
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toHaveCount(0);

        // ── 2. Reload so the next count can only come from the server ──
        await page.reload();
        await expect(card).toBeVisible();
        await ring(page);
        await expect(page.getByRole('button', { name: /Snooze \(1\/2 used\)/ })).toBeVisible();
        // The escalation banner proves the anti-snooze rule is applied, not just counted.
        await expect(page.getByText(/Anti-snooze active/i)).toBeVisible();
        await page.getByRole('button', { name: /Snooze \(1\/2 used\)/ }).click();
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toHaveCount(0);

        // ── 3. Third ring — the limit is reached and snoozing is refused ──
        await page.reload();
        await expect(card).toBeVisible();
        await ring(page);
        await expect(page.getByRole('button', { name: /Snooze \(/ })).toHaveCount(0);
        await expect(page.getByText(/Snooze limit reached \(2\/2\)/)).toBeVisible();

        // ── 4. Give up — an explicit failed wake, confirmed through the dialog ──
        page.once('dialog', (dialog) => {
            expect(dialog.message()).toContain('failed wake');
            return dialog.accept();
        });
        await page.getByRole('button', { name: 'Give up this wake' }).click();

        await expect(page.getByText(/Wake cycle abandoned/i).first()).toBeVisible();
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toHaveCount(0);

        // ── 5. The abandoned cycle really closed: the page still works afterwards ──
        await page.reload();
        await expect(card).toBeVisible();
        await navigateTo(page, 'Dashboard', '/dashboard');
        await expect(page.getByText(account.email).first()).toBeVisible();
    });

    test('the ringing modal blocks the page until the wake cycle is resolved', async ({ page }) => {
        await login(page, account);
        await navigateTo(page, 'Alarms', '/alarms');
        await ring(page);

        // The modal is a full-screen overlay, so the nav underneath is unreachable.
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toBeVisible();
        await expect(page.getByText(/Solve the challenge to turn off the alarm/i)).toBeVisible();

        page.once('dialog', (dialog) => dialog.accept());
        await page.getByRole('button', { name: 'Give up this wake' }).click();
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toHaveCount(0);

        // With the overlay gone the app is navigable again.
        await navigateTo(page, 'Reports', '/reports');
        await expect(page.getByRole('heading', { name: 'Lifestyle Reports' })).toBeVisible();
    });
});
