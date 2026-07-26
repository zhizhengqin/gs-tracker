// scripts/ui_snapshot.js — snapshot dashboard views at a given viewport.
// Usage: node scripts/ui_snapshot.js <url> <width> <height> <outdir>
// Drawer-aware: opens the hamburger drawer first when the mobile topbar exists.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

async function navTo(pg, view) {
    const btn = await pg.$('.mobile-topbar .menu-btn');
    if (btn && await btn.isVisible()) { await btn.click(); await pg.waitForTimeout(400); }
    await pg.click(`li[data-view="${view}"]`);
    await pg.waitForTimeout(1200);
}

(async () => {
    const [url, w, h, outdir] = process.argv.slice(2);
    fs.mkdirSync(outdir, { recursive: true });
    const b = await pw.chromium.launch();
    const pg = await b.newPage({ viewport: { width: +w, height: +h } });
    await pg.goto(url, { waitUntil: 'networkidle' });
    await pg.waitForTimeout(800);
    await pg.screenshot({ path: path.join(outdir, '1_daily.png'), fullPage: true });
    await navTo(pg, 'settings');
    await pg.screenshot({ path: path.join(outdir, '2_settings.png'), fullPage: true });
    await navTo(pg, 'quarter');
    await pg.screenshot({ path: path.join(outdir, '3_quarter.png'), fullPage: true });
    await b.close();
    console.log('saved to ' + outdir);
})();
