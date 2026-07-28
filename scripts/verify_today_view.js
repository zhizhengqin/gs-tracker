// scripts/verify_today_view.js — today-view structure assertions at 390px + 1280px.
// Usage: node scripts/verify_today_view.js <url> <outdir>
// Exit 0 = all checks pass. Screenshots saved to <outdir>.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

const URL_ = process.argv[2] || 'http://127.0.0.1:8770';
const OUT = process.argv[3] || '/tmp/gs_today_verify';
const failures = [];
function check(name, ok) {
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    if (!ok) failures.push(name);
}
// The app requires login; sign in if we land on the login page.
// Credentials come from GS_VERIFY_USER / GS_VERIFY_PASS (default: built-in admin).
async function loginIfNeeded(pg) {
    if (await pg.$('#login-form')) {
        await pg.fill('#username', process.env.GS_VERIFY_USER || 'gsadmin');
        await pg.fill('#password', process.env.GS_VERIFY_PASS || 'admin123');
        await pg.click('#login-btn');
        await pg.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 10000 });
        await pg.waitForLoadState('networkidle');
    }
}
process.on('unhandledRejection', e => {
    console.log('FAIL  exception: ' + e.message);
    process.exit(1);
});

(async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const b = await pw.chromium.launch();
    for (const [w, h, tag] of [[390, 844, 'mobile'], [1280, 900, 'desktop']]) {
        const pg = await b.newPage({ viewport: { width: w, height: h } });
        await pg.goto(URL_, { waitUntil: 'networkidle' });
        await loginIfNeeded(pg);
        await pg.waitForTimeout(1200);

        check(tag + ': report container above today feed', await pg.evaluate(() => {
            const rc = document.getElementById('dailyReportContainer');
            const tf = document.getElementById('todayFeed');
            if (!rc || !tf) return false;
            return !!(rc.compareDocumentPosition(tf) & Node.DOCUMENT_POSITION_FOLLOWING);
        }));

        check(tag + ': earlier section collapsed by default', await pg.evaluate(() => {
            const body = document.getElementById('earlierBody');
            return body && body.style.display === 'none';
        }));

        await pg.click('#earlierToggle');
        await pg.waitForTimeout(1500);
        check(tag + ': earlier expands with day selector', await pg.evaluate(() => {
            const body = document.getElementById('earlierBody');
            return body && body.style.display !== 'none' && !!body.querySelector('.day-selector');
        }));
        await pg.screenshot({ path: path.join(OUT, tag + '_today_expanded.png'), fullPage: true });

        await pg.evaluate(() => { document.getElementById('dailyDatePicker').value = '2026-07-24'; });
        await pg.click('.daily-header .date-picker-row .btn-sm.primary');
        await pg.waitForTimeout(1200);
        check(tag + ': historical view offers back-to-today', await pg.evaluate(() =>
            [...document.querySelectorAll('button')].some(b => b.textContent.includes('返回今日'))
        ));
        check(tag + ': historical report above feed', await pg.evaluate(() => {
            const rc = document.getElementById('dailyReportContainer');
            const feed = document.querySelector('.daily-feed');
            if (!rc || !feed) return false;
            return !!(rc.compareDocumentPosition(feed) & Node.DOCUMENT_POSITION_FOLLOWING);
        }));
        await pg.screenshot({ path: path.join(OUT, tag + '_historical.png'), fullPage: true });

        await pg.click('button:has-text("返回今日")');
        await pg.waitForTimeout(1200);
        check(tag + ': back-to-today restores today view', await pg.evaluate(() =>
            !!document.getElementById('todayFeed')
        ));
        await pg.close();
    }
    await b.close();
    console.log(failures.length ? `\n${failures.length} FAIL` : '\nALL PASS');
    process.exit(failures.length ? 1 : 0);
})();
