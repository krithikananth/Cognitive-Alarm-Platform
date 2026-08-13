const { test, expect } = require('@playwright/test');
const { ACCOUNTS } = require('../helpers/accounts');
const { login } = require('../helpers/app');

const admin = ACCOUNTS.admin;
const coach = ACCOUNTS.coach;
const seededClient = ACCOUNTS.user;
// Not on the coach's roster when the suite starts, so assigning it is real work.
const newClient = ACCOUNTS.unverified;

/** The coach-assignment card on the admin page. */
function panel(page) {
    return page
        .locator('.card')
        .filter({ has: page.getByRole('heading', { name: 'Coach Assignments' }) });
}

/** Open the coach roster in a clean context so the admin session is not reused. */
async function openCoachRoster(browser, page) {
    const context = await browser.newContext({ baseURL: new URL(page.url()).origin });
    const coachPage = await context.newPage();
    await login(coachPage, coach);
    await expect(coachPage).toHaveURL(/\/wellness$/);
    return { context, coachPage };
}

test.describe('Journey: admin assigns a client to a wellness coach', () => {
    test('an assignment created in the admin UI grants the coach access, and removing it revokes access', async ({
        browser,
        page,
    }) => {
        await login(page, admin);
        await expect(page).toHaveURL(/\/admin$/);

        // ── 1. The panel exists and shows the seeded assignment ──
        const assignments = panel(page);
        await expect(assignments.getByRole('heading', { name: 'Coach Assignments' })).toBeVisible();
        await expect(
            assignments.getByRole('row').filter({ hasText: seededClient.email })
        ).toBeVisible();

        // The client we are about to assign is not on the roster yet.
        await expect(
            assignments.getByRole('row').filter({ hasText: newClient.email })
        ).toHaveCount(0);

        // ── 2. Create the assignment through the form ──
        await assignments
            .locator('select[aria-label="Coach"]')
            .selectOption({ label: `${coach.fullName} (${coach.email})` });
        await assignments
            .locator('select[aria-label="Client"]')
            .selectOption({ label: `${newClient.fullName} (${newClient.email})` });
        await assignments
            .locator('input[aria-label="Assignment notes"]')
            .fill('Added by the end-to-end journey');
        await assignments.getByRole('button', { name: 'Assign' }).click();

        const newRow = assignments.getByRole('row').filter({ hasText: newClient.email });
        await expect(newRow).toBeVisible();
        await expect(newRow.getByText('Active')).toBeVisible();
        await expect(newRow.getByText('Added by the end-to-end journey')).toBeVisible();

        // ── 3. The coach can now actually see that client ──
        const granted = await openCoachRoster(browser, page);
        await expect(
            granted.coachPage
                .locator('#coach-clients')
                .getByRole('button')
                .filter({ hasText: newClient.email })
        ).toBeVisible();
        await granted.context.close();

        // ── 4. Removing it goes through an explicit confirmation ──
        await newRow.getByLabel(`Remove ${newClient.username} from ${coach.username}`).click();
        await expect(page.getByRole('heading', { name: 'Remove assignment?' })).toBeVisible();
        await page.getByRole('button', { name: 'Remove', exact: true }).click();

        await expect(assignments.getByRole('row').filter({ hasText: newClient.email })).toHaveCount(0);

        // ── 5. Access is revoked, and the original roster is untouched ──
        const revoked = await openCoachRoster(browser, page);
        const roster = revoked.coachPage.locator('#coach-clients');
        await expect(
            roster.getByRole('button').filter({ hasText: seededClient.email })
        ).toBeVisible();
        await expect(
            roster.getByRole('button').filter({ hasText: newClient.email })
        ).toHaveCount(0);
        await revoked.context.close();

        // ── 6. The removed row is retained for audit, not deleted ──
        await assignments.getByText('Show removed').click();
        const archived = assignments.getByRole('row').filter({ hasText: newClient.email });
        await expect(archived).toBeVisible();
        await expect(archived.getByText('Removed')).toBeVisible();
    });
});
