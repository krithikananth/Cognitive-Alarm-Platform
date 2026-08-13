/**
 * Shared browser actions for the end-to-end journeys.
 *
 * Everything here drives the real UI — forms, nav links, buttons — so the
 * specs exercise the same paths a person would instead of seeding state
 * through the API.
 */
const { expect } = require('@playwright/test');

/**
 * Sign in through the login form and wait for the post-login landing page.
 *
 * The auth store flips `isAuthenticated` (which redirects immediately) but
 * then keeps awaiting a timezone sync and a profile fetch, after which the
 * login page issues a *second* `navigate()`. Returning before that lands
 * would let the late navigation yank the test off the page it moved to, so
 * the profile request is awaited first.
 */
async function login(page, account, { password } = {}) {
    await page.goto('/login');
    await page.locator('#login-email').fill(account.email);
    await page.locator('#login-password').fill(password || account.password);

    const profileSettled = page.waitForResponse(
        (res) => res.url().includes('/users/profile') && res.request().method() === 'GET',
        { timeout: 45_000 }
    );
    await page.locator('#login-submit').click();
    await profileSettled;

    await page.waitForURL((url) => !url.pathname.startsWith('/login'), {
        timeout: 30_000,
    });
    return page;
}

/**
 * Sign out so the session cookie is really cleared.
 *
 * The coach workspace renders its own header logout next to the sidebar one,
 * so the first match is taken deliberately.
 *
 * The URL flips to `/login` before the login page has mounted, and its own
 * effects can still issue a navigation afterwards. A caller that navigated
 * immediately had its document request aborted by that late redirect
 * (`net::ERR_ABORTED`), so the login form is awaited here as the settle point.
 */
async function logout(page) {
    await page.getByRole('button', { name: 'Logout' }).first().click();
    await page.waitForURL(/\/login/);
    await expect(page.locator('#login-email')).toBeVisible();
}

/**
 * Move between pages the way a user does: click the sidebar entry and wait
 * for the route to commit.
 *
 * The URL is polled rather than awaited as a navigation event, because these
 * are client-side route changes with no document load behind them.
 */
async function navigateTo(page, label, pathname) {
    await page.getByRole('link', { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${pathname}$`), { timeout: 30_000 });
}

module.exports = { login, logout, navigateTo };
