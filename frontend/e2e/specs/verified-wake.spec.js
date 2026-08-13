const { test, expect } = require('@playwright/test');
const { ACCOUNTS, VERIFIED_WAKE_ALARM_TITLE } = require('../helpers/accounts');
const { login, navigateTo } = require('../helpers/app');

const account = ACCOUNTS.waker;

/**
 * Evaluate the arithmetic the MATH generator prints.
 *
 * The correct answer is never sent to the browser — verification is entirely
 * server-side — so the only honest way to solve the challenge is to read the
 * rendered prompt and do the arithmetic, exactly as a person does. Grammar
 * matches `_generate_math`: integers, `+ - * × ÷` and parentheses, evaluated
 * with normal precedence.
 */
function evaluateEquation(equation) {
    const tokens = equation
        .replace(/×/g, '*')
        .replace(/÷/g, '/')
        .match(/\d+|[+\-*/()]/g);
    if (!tokens) throw new Error(`Unparseable equation: ${equation}`);

    let index = 0;
    const peek = () => tokens[index];

    function factor() {
        const token = tokens[index++];
        if (token === '(') {
            const value = expression();
            if (tokens[index++] !== ')') throw new Error(`Unbalanced parentheses: ${equation}`);
            return value;
        }
        if (token === '-') return -factor();
        const value = Number(token);
        if (Number.isNaN(value)) throw new Error(`Unexpected token "${token}" in ${equation}`);
        return value;
    }

    function term() {
        let value = factor();
        while (peek() === '*' || peek() === '/') {
            value = tokens[index++] === '*' ? value * factor() : value / factor();
        }
        return value;
    }

    function expression() {
        let value = term();
        while (peek() === '+' || peek() === '-') {
            value = tokens[index++] === '+' ? value + term() : value - term();
        }
        return value;
    }

    const result = expression();
    if (index !== tokens.length) throw new Error(`Trailing tokens in ${equation}`);
    return result;
}

/** Ring the alarm from its card and wait for a MATH challenge to be served. */
async function ringMathChallenge(page) {
    const card = page.locator('.card').filter({ hasText: VERIFIED_WAKE_ALARM_TITLE });
    await expect(card).toBeVisible();

    const heading = page.getByRole('heading', { name: 'WAKE UP!' });
    // The alarm list re-renders as the upcoming-alarms fetch lands, which can
    // detach the button mid-click. Retrying is safe because the first branch
    // makes the block a no-op once the modal is actually open.
    await expect(async () => {
        if (await heading.count()) return;
        await card.getByTitle('Test Ring').click({ timeout: 5_000 });
        await expect(heading).toBeVisible({ timeout: 5_000 });
    }).toPass({ timeout: 45_000 });

    // The alarm pins MATH, so anything else means the served type regressed
    // and the answer below would be a guess.
    await expect(page.getByText('MATH CHALLENGE')).toBeVisible();

    const prompt = page.getByText(/^Solve: .+ = \?$/);
    await expect(prompt).toBeVisible();
    const text = await prompt.innerText();
    const equation = text.replace(/^Solve:/, '').replace(/=\s*\?$/, '').trim();
    return String(evaluateEquation(equation));
}

test.describe('Journey: ringing alarm → challenge solved → verified wake', () => {
    test('solving the challenge dismisses the alarm and the wake reaches the dashboard', async ({
        page,
    }) => {
        await login(page, account);

        // ── 1. Before: this account has never completed a wake ──
        await expect(page).toHaveURL(/\/dashboard$/);
        // The dashboard fans out to a dozen requests on mount, so the first
        // paint of this panel can lag well past the default expect timeout
        // when the whole suite is running.
        await expect(page.getByText(/No wake events yet\./)).toBeVisible({
            timeout: 30_000,
        });

        // ── 2. Ring the alarm and answer the served challenge correctly ──
        await navigateTo(page, 'Alarms', '/alarms');
        const answer = await ringMathChallenge(page);
        await page.getByRole('button', { name: answer, exact: true }).click();

        // ── 3. The modal closes only because the server accepted the answer ──
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toHaveCount(0, {
            timeout: 30_000,
        });

        // ── 4. After: the same panel now reports a completed wake ──
        await navigateTo(page, 'Dashboard', '/dashboard');
        await expect(page.getByText(/No wake events yet\./)).toHaveCount(0, {
            timeout: 30_000,
        });
        // Panel-unique labels: the KPI strip also carries a "Success Rate" card.
        await expect(page.getByText('First-try rate')).toBeVisible();
        await expect(page.getByText('Overall accuracy')).toBeVisible();

        // ── 5. A reload proves it was persisted, not held in the store ──
        await page.reload();
        await expect(page.getByText('First-try rate')).toBeVisible();
        await expect(page.getByText(/No wake events yet\./)).toHaveCount(0);
    });

    test('a wrong answer is refused by the server and the alarm keeps ringing', async ({ page }) => {
        await login(page, account);
        await navigateTo(page, 'Alarms', '/alarms');

        const answer = await ringMathChallenge(page);
        const options = page.locator('button', { hasText: /^-?\d+$/ });
        const values = await options.allInnerTexts();
        const wrong = values.map((v) => v.trim()).find((v) => v !== answer);
        expect(wrong, 'the challenge must offer at least one incorrect option').toBeTruthy();

        await page.getByRole('button', { name: wrong, exact: true }).click();

        await expect(page.getByText(/Incorrect answer/i)).toBeVisible({ timeout: 30_000 });
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toBeVisible();

        // Close the cycle explicitly so it does not leak into a later run.
        page.once('dialog', (dialog) => dialog.accept());
        await page.getByRole('button', { name: 'Give up this wake' }).click();
        await expect(page.getByRole('heading', { name: 'WAKE UP!' })).toHaveCount(0, {
            timeout: 30_000,
        });
    });
});
