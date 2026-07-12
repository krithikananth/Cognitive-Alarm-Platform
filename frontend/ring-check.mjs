const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const logs = [];
  page.on('console', msg => {
    const t = msg.text();
    if (t.includes('AlarmWatcher') || t.includes('WAKE') || t.includes('error')) logs.push(t);
  });

  await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
  await page.fill('input[type="email"], input[name="email"]', 'explorer11@test.com');
  await page.fill('input[type="password"], input[name="password"]', 'TestPass123!');
  await page.click('button[type="submit"]');
  await page.waitForURL(/dashboard|alarms|profile/, { timeout: 15000 });

  // Wait up to 90s for WAKE UP modal (alarm 22 ~14:34 UTC)
  let found = false;
  try {
    await page.getByText('WAKE UP!', { exact: true }).waitFor({ timeout: 90000 });
    found = true;
  } catch (e) {
    found = false;
  }

  const hasBell = await page.locator('svg').count() > 0;
  const hasChallenge = await page.getByText(/CHALLENGE/i).count() > 0;
  const challengePrompt = await page.locator('.text-2xl.font-bold.text-white, .text-4xl.font-bold').first().textContent().catch(() => null);
  const bodyText = found ? await page.locator('body').innerText() : '';

  // AudioContext exists when ringing (can't hear in headless, but code path runs)
  const audioStarted = await page.evaluate(() => typeof AudioContext !== 'undefined' || typeof webkitAudioContext !== 'undefined');

  console.log(JSON.stringify({
    scheduledRing: found,
    hasWakeUp: found,
    hasChallengeLabel: hasChallenge,
    challengePrompt,
    audioApiAvailable: audioStarted,
    url: page.url(),
    logs: logs.slice(-10),
    snippet: bodyText.slice(0, 500)
  }, null, 2));

  if (!found) {
    // Fallback: Test Ring button to verify modal UI itself
    await page.goto('http://localhost:3000/alarms', { waitUntil: 'networkidle' });
    const testBtn = page.getByTitle('Test Ring').first();
    if (await testBtn.count()) {
      await testBtn.click();
      await page.getByText('WAKE UP!', { exact: true }).waitFor({ timeout: 15000 });
      const testChallenge = await page.getByText(/CHALLENGE/i).count() > 0;
      const prompt = await page.locator('.text-2xl.font-bold.text-white').first().textContent().catch(() => null);
      console.log(JSON.stringify({ testRingFallback: true, hasWakeUp: true, hasChallengeLabel: testChallenge, prompt }, null, 2));
    } else {
      console.log(JSON.stringify({ testRingFallback: false, reason: 'no Test Ring button' }, null, 2));
    }
  }

  await page.screenshot({ path: 'ring-test-result.png', fullPage: true });
  await browser.close();
})().catch(err => { console.error('FATAL', err); process.exit(1); });
