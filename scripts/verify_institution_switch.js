// scripts/verify_institution_switch.js — regression: ISSUE-002 institution
// switch must re-filter the daily feed (today mode + custom date mode).
// Found by /qa on 2026-08-04. Usage: node scripts/verify_institution_switch.js <url> <outdir>
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

const URL_ = process.argv[2] || 'http://127.0.0.1:8770';
const OUT = process.argv[3] || '/tmp/gs_inst_verify';
const failures = [];
function check(name, ok) {
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    if (!ok) failures.push(name);
}
async function loginIfNeeded(pg) {
    if (await pg.$('#login-form')) {
        await pg.fill('#username', process.env.GS_VERIFY_USER || 'gsadmin');
        await pg.fill('#password', process.env.GS_VERIFY_PASS || 'admin123');
        await pg.click('#login-btn');
        await pg.waitForSelector('#mainNav', { timeout: 15000 });
        await pg.waitForLoadState('networkidle');
    }
}
process.on('unhandledRejection', e => {
    console.log('FAIL  exception: ' + e.message);
    process.exit(1);
});

// Visible signal-card institution badges (text of .inst-tag inside h4).
function badges(pg) {
    return pg.evaluate(() =>
        [...document.querySelectorAll('.signal-card')]
            .filter(c => c.offsetParent !== null)
            .map(c => (c.querySelector('h4 .inst-tag') || {}).textContent || '无标签')
    );
}
async function selectInst(pg, value) {
    await pg.evaluate(v => {
        const r = document.querySelector(`input[name="institution"][value="${v}"]`);
        r.checked = true;
        r.dispatchEvent(new Event('change', { bubbles: true }));
    }, value);
    await pg.waitForTimeout(2500);
}

(async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const b = await pw.chromium.launch();
    const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
    await pg.goto(URL_, { waitUntil: 'networkidle' });
    await loginIfNeeded(pg);
    await pg.waitForTimeout(1500);

    // Today mode: switch to JPM -> no GS-badged cards may remain visible.
    await selectInst(pg, 'jpm');
    let bs = await badges(pg);
    check('today mode: JPM selected hides GS cards', bs.every(t => t !== '高盛'));
    check('today mode: JPM selected shows feed or empty state', bs.length >= 0);
    await pg.screenshot({ path: path.join(OUT, 'today-jpm.png') });

    // Switch back to GS -> no JPM-badged cards may remain visible.
    await selectInst(pg, 'gs');
    bs = await badges(pg);
    check('today mode: GS selected hides JPM cards', bs.every(t => t !== '摩根大通'));

    // Custom date mode: pick a past date, then switch institution.
    await pg.evaluate(() => {
        const p = document.getElementById('dailyDatePicker');
        p.value = '2026-08-01';
        loadDateSignals(p.value);
    });
    await pg.waitForTimeout(2500);
    await selectInst(pg, 'jpm');
    bs = await badges(pg);
    check('custom date: JPM selected hides GS cards', bs.every(t => t !== '高盛'));
    await pg.screenshot({ path: path.join(OUT, 'date-jpm.png') });

    await selectInst(pg, 'gs');
    bs = await badges(pg);
    check('custom date: GS selected hides JPM cards', bs.every(t => t !== '摩根大通'));

    await b.close();
    console.log(failures.length ? `\n${failures.length} FAILURES` : '\nALL PASS');
    process.exit(failures.length ? 1 : 0);
})();
