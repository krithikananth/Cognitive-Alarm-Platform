const fs = require('fs');
const { test, expect } = require('@playwright/test');
const { ACCOUNTS } = require('../helpers/accounts');
const { login, navigateTo } = require('../helpers/app');

const account = ACCOUNTS.user;

/** Click an export button and return the file the browser actually received. */
async function exportReport(page, format) {
    const [download] = await Promise.all([
        page.waitForEvent('download', { timeout: 60_000 }),
        page.getByRole('button', { name: format, exact: true }).click(),
    ]);
    const path = await download.path();
    return { name: download.suggestedFilename(), size: fs.statSync(path).size };
}

test.describe('Journey: user exports a lifestyle report', () => {
    test('a report is previewed then downloaded as PDF and Excel', async ({ page }) => {
        await login(page, account);

        // ── 1. Cross into Reports from the dashboard ──
        await navigateTo(page, 'Reports', '/reports');
        await expect(page.getByRole('heading', { name: 'Lifestyle Reports' })).toBeVisible();

        // The preview must finish loading before exporting is allowed.
        const pdfButton = page.getByRole('button', { name: 'PDF', exact: true });
        await expect(pdfButton).toBeEnabled();

        // ── 2. PDF export produces a real file ──
        const pdf = await exportReport(page, 'PDF');
        expect(pdf.name).toMatch(/\.pdf$/);
        expect(pdf.size).toBeGreaterThan(1000);

        // ── 3. Excel export of the same report ──
        const excel = await exportReport(page, 'Excel');
        expect(excel.name).toMatch(/\.xlsx$/);
        expect(excel.size).toBeGreaterThan(1000);
    });

    test('switching report type and date window changes what is exported', async ({ page }) => {
        await login(page, account);
        await navigateTo(page, 'Reports', '/reports');

        // ── 1. Pick a different report and a different window ──
        await page.getByRole('button', { name: /Challenge Performance/ }).click();
        await page.getByRole('button', { name: '7 days', exact: true }).click();

        const pdfButton = page.getByRole('button', { name: 'PDF', exact: true });
        await expect(pdfButton).toBeEnabled();

        // ── 2. The exported file is named for the selected report ──
        const challenge = await exportReport(page, 'PDF');
        expect(challenge.name).toMatch(/challenge/i);
        expect(challenge.size).toBeGreaterThan(1000);

        // ── 3. Switching back yields the habit report again ──
        await page.getByRole('button', { name: /Habit Report/ }).click();
        await expect(pdfButton).toBeEnabled();
        const habit = await exportReport(page, 'PDF');
        expect(habit.name).toMatch(/habit/i);
        expect(habit.name).not.toBe(challenge.name);
    });
});
