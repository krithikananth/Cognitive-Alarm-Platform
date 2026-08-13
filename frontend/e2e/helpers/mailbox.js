/**
 * Test mailbox.
 *
 * No SMTP server runs during the suite, so the backend logs the body of every
 * transactional email instead of sending it. Reading those records back gives
 * the specs the same one-time links a real user would click, which is what
 * makes the verification and password-reset journeys genuinely end to end
 * rather than a token minted behind the UI's back.
 */
const fs = require('fs');
const path = require('path');

const LOG_DIR = path.resolve(__dirname, '..', '..', '..', 'backend', '.e2e', 'logs');

function readLogRecords() {
    let files;
    try {
        files = fs.readdirSync(LOG_DIR).filter((name) => name.includes('.log'));
    } catch {
        return [];
    }

    const records = [];
    for (const name of files) {
        let raw;
        try {
            raw = fs.readFileSync(path.join(LOG_DIR, name), 'utf8');
        } catch {
            continue;
        }
        for (const line of raw.split('\n')) {
            if (!line.trim()) continue;
            try {
                records.push(JSON.parse(line));
            } catch {
                // A record can be torn mid-write while the server is still running.
            }
        }
    }
    return records.sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
}

/**
 * Return the most recent link of `kind` addressed to `email`.
 *
 * @param {'verify-email'|'reset-password'} kind SPA path carried by the link.
 * @param {string} email Recipient the message was logged for.
 * @returns {{url: string, token: string}|null}
 */
function findLink(kind, email) {
    const pattern = new RegExp(`(https?://[^\\s"]*?/${kind}\\?token=([A-Za-z0-9._~%-]+))`);
    const matches = readLogRecords()
        .filter((record) => typeof record.message === 'string')
        .filter((record) => record.message.includes(email))
        .map((record) => record.message.match(pattern))
        .filter(Boolean);

    const last = matches[matches.length - 1];
    return last ? { url: last[1], token: last[2] } : null;
}

/**
 * Poll the mailbox until the link arrives.
 *
 * @returns {Promise<{url: string, token: string}>}
 */
async function waitForLink(kind, email, { timeout = 20_000, interval = 250 } = {}) {
    const deadline = Date.now() + timeout;
    let found = findLink(kind, email);
    while (!found && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, interval));
        found = findLink(kind, email);
    }
    if (!found) {
        throw new Error(
            `No ${kind} link for ${email} appeared in the backend mail log (${LOG_DIR}) within ${timeout}ms`
        );
    }
    return found;
}

/** Path part of a mailed link, so specs can navigate relative to baseURL. */
function toRelative(url) {
    const parsed = new URL(url);
    return `${parsed.pathname}${parsed.search}`;
}

module.exports = { LOG_DIR, findLink, waitForLink, toRelative };
