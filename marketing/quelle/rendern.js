// Rendert Filme (MP4) und Standbilder aus den HTML-Vorlagen.
// Aufruf: node rendern.js film <film> <fmt> <ziel.mp4> | probe <film> <fmt> <t1,t2,...> <ordner>
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs"), path = require("path");
const GROESSE = { story: [1080, 1920], square: [1080, 1080], wide: [1920, 1080] };
(async () => {
  const [modus, film, fmt, a, b] = process.argv.slice(2);
  const [w, h] = GROESSE[fmt];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  await page.goto("file://" + path.join(__dirname, `film.html?film=${film}&fmt=${fmt}`));
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  if (modus === "probe") {
    for (const t of a.split(",").map(Number)) {
      await page.evaluate((t) => setzeZeit(t), t);
      await page.screenshot({ path: path.join(b, `${film}_${fmt}_${t}.png`) });
    }
  } else {
    const dauer = await page.evaluate(() => window.FILMDAUER);
    const fps = 30, n = Math.round(dauer * fps);
    const tmp = fs.mkdtempSync(path.join(process.env.TMPDIR || "/tmp", "frames-"));
    for (let i = 0; i < n; i++) {
      await page.evaluate((t) => setzeZeit(t), i / fps);
      await page.screenshot({ path: path.join(tmp, String(i).padStart(5, "0") + ".jpg"), type: "jpeg", quality: 92 });
    }
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(fps), "-i", path.join(tmp, "%05d.jpg"),
      "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest",
      "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
      "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", a]);
    fs.rmSync(tmp, { recursive: true });
    console.log("fertig:", a, n, "Bilder");
  }
  await browser.close();
})();
