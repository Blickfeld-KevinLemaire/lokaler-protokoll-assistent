// Rendert alle Standbilder, das LinkedIn-Karussell und die Präsentation.
const { chromium } = require("playwright");
const path = require("path"), fs = require("fs");
const G = { portrait: [1080, 1350], square: [1080, 1080], story: [1080, 1920], linkedin: [1200, 627], wide: [1920, 1080] };
const AUS = path.join(__dirname, "..");
const KARUSSELL = ["hook", "aufnehmen", "sprecher", "protokoll", "frag", "datenschutz", "raum", "cta"];
const FOLIEN = ["hero", "aufnehmen", "sprecher", "protokoll", "frag", "datenschutz", "raum", "cta"];
const auftraege = [];
for (const f of ["portrait", "square", "story", "linkedin"]) auftraege.push(["hero", f, `bilder/posts/vermerk_hero_${f}.png`, ""]);
for (const m of ["protokoll", "frag", "datenschutz", "raum"]) for (const f of ["square", "portrait", "linkedin"]) auftraege.push([m, f, `bilder/posts/vermerk_${m}_${f}.png`, ""]);
KARUSSELL.forEach((m, i) => auftraege.push([m, "portrait", `bilder/karussell/karussell_${i + 1}_${m}.png`, `&nr=${i + 1}&von=${KARUSSELL.length}${i === 0 ? "&wischen=1" : ""}`]));
FOLIEN.forEach((m, i) => auftraege.push([m, "wide", `praesentation/folie_${i + 1}_${m}.png`, `&nr=${i + 1}&von=${FOLIEN.length}`]));
(async () => {
  const browser = await chromium.launch();
  for (const [m, f, ziel, extra] of auftraege) {
    const [w, h] = G[f];
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
    await page.goto("file://" + path.join(__dirname, `bilder.html?motiv=${m}&fmt=${f}${extra}`));
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(150);
    fs.mkdirSync(path.dirname(path.join(AUS, ziel)), { recursive: true });
    await page.screenshot({ path: path.join(AUS, ziel) });
    await page.close();
  }
  await browser.close();
  console.log(auftraege.length, "Bilder");
})();
