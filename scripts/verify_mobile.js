// scripts/verify_mobile.js — mobile layout assertions at 390x844 (iPhone-ish).
// Usage: node scripts/verify_mobile.js <url> <outdir>
// Exit 0 = all checks pass. Screenshots saved to <outdir> for eyeball review.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

const URL_ = process.argv[2] || 'http://127.0.0.1:8770';
const OUT = process.argv[3] || '/tmp/gs_mobile_verify';
const failures = [];
function check(name, ok) {
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    if (!ok) failures.push(name);
}
process.on('unhandledRejection', e => {
    console.log('FAIL  exception: ' + e.message);
    process.exit(1);
});

(async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const b = await pw.chromium.launch();
    const pg = await b.newPage({ viewport: { width: 390, height: 844 } });
    await pg.goto(URL_, { waitUntil: 'networkidle' });
    await pg.waitForTimeout(800);
    const noX = () => pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    const drawerOpen = () => pg.evaluate(() => document.querySelector('.sidebar').classList.contains('open'));

    check('daily: no horizontal overflow', await noX());

    await pg.click('.mobile-topbar .menu-btn'); await pg.waitForTimeout(400);
    check('drawer opens', await drawerOpen());
    await pg.screenshot({ path: path.join(OUT, 'drawer_open.png') });

    await pg.click('.mobile-mask'); await pg.waitForTimeout(400);
    check('mask closes drawer', !(await drawerOpen()));

    await pg.click('.mobile-topbar .menu-btn'); await pg.waitForTimeout(400);
    await pg.click('li[data-view="settings"]'); await pg.waitForTimeout(1200);
    check('drawer auto-closes after nav', !(await drawerOpen()));
    check('settings: no horizontal overflow', await noX());
    await pg.screenshot({ path: path.join(OUT, 'settings.png'), fullPage: true });

    await pg.click('.mobile-topbar .menu-btn'); await pg.waitForTimeout(400);
    await pg.click('li[data-view="quarter"]'); await pg.waitForTimeout(1200);
    check('quarter: no horizontal overflow', await noX());
    await pg.screenshot({ path: path.join(OUT, 'quarter.png'), fullPage: true });

    await pg.evaluate(() => showProgressPanel());
    await pg.waitForTimeout(300);
    const r = await pg.evaluate(() => {
        const x = document.getElementById('progressPanel').getBoundingClientRect();
        return { left: x.left, right: x.right };
    });
    check('progress panel within viewport', r.left >= 0 && r.right <= 390);
    await pg.screenshot({ path: path.join(OUT, 'progress.png') });

    await b.close();
    console.log(failures.length ? `\n${failures.length} FAIL` : '\nALL PASS');
    process.exit(failures.length ? 1 : 0);
})();
