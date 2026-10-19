const puppeteer = require('/home/fsociety/dl_exam_pres/node_modules/puppeteer');
const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');

const root = __dirname;
const pdfPath = path.join(root, 'DocDesk_Presentation.pdf');
const pptxPath = path.join(root, 'DocDesk_Presentation.pptx');
const chrome = '/home/fsociety/.cache/puppeteer/chrome/linux-151.0.7922.71/chrome-linux64/chrome';

(async () => {
  const browser = await puppeteer.launch({ headless: 'new', executablePath: chrome,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 900, deviceScaleFactor: 1.5 });
  await page.goto('file://' + path.join(root, 'index.html'), { waitUntil: 'load', timeout: 60000 });
  await page.addStyleTag({ content: 'html,body{width:1600px!important;height:900px!important;overflow:hidden!important}.topbar,.progress,.bottom-nav,.overview{display:none!important}#deck{width:1600px!important;height:900px!important;overflow:hidden!important}.slide{display:none!important;position:absolute!important;inset:0!important;width:1600px!important;height:900px!important;padding:64px 128px!important;overflow:hidden!important;animation:none!important}.slide.active{display:flex!important}' });
  await page.evaluate(() => document.fonts.ready);
  const renderDir = path.join(root, 'renders');
  fs.mkdirSync(renderDir, { recursive: true });
  const pdfPages = [];
  for (let i = 0; i < 12; i++) {
    await page.evaluate(n => document.querySelectorAll('.slide').forEach((s, j) => s.classList.toggle('active', j === n)), i);
    await new Promise(resolve => setTimeout(resolve, 80));
    const name = 'slide-' + String(i + 1).padStart(2, '0');
    const pngPath = path.join(renderDir, name + '.png');
    await page.screenshot({ path: pngPath, type: 'png' });
    const printPage = await browser.newPage();
    const png = fs.readFileSync(pngPath).toString('base64');
    await printPage.setContent('<html><style>@page{size:16in 9in;margin:0}html,body{margin:0;width:16in;height:9in;overflow:hidden}img{width:16in;height:9in;display:block}</style><img src="data:image/png;base64,' + png + '"></html>');
    const onePdf = path.join(renderDir, name + '.pdf');
    await printPage.pdf({ path: onePdf, width: '16in', height: '9in', printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
    pdfPages.push(onePdf);
    await printPage.close();
  }
  await browser.close();
  execFileSync('pdfunite', [...pdfPages, pdfPath]);
  execFileSync('python3', [path.join(root, 'build_pptx.py')], { stdio: 'inherit' });
  console.log('Wrote ' + pdfPath + ' (' + (fs.statSync(pdfPath).size / 1024 / 1024).toFixed(1) + ' MB)');
  console.log('Wrote ' + pptxPath + ' (' + (fs.statSync(pptxPath).size / 1024 / 1024).toFixed(1) + ' MB)');
})().catch(err => { console.error(err); process.exit(1); });
