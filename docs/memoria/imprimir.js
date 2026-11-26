// Imprime un HTML a PDF A4 con el encabezado y el número de página del formato de apuntes.
// Uso: node imprimir.js entrada.html salida.pdf
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const [entrada, salida] = process.argv.slice(2);
  const navegador = await chromium.launch();
  const pagina = await navegador.newPage();
  await pagina.goto('file://' + path.resolve(entrada), { waitUntil: 'networkidle' });
  await pagina.evaluate(() => document.fonts.ready);
  const estilo = "font-family:Georgia,serif;font-size:7.5pt;color:#6B6F78;";
  await pagina.pdf({
    path: salida,
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: `<div style="${estilo}width:100%;padding:0 17mm;text-align:right;line-height:1.35;margin-top:6mm">
      Conserje IA<br>Práctica final · Deep Learning para Business Analytics</div>`,
    footerTemplate: `<div style="${estilo}width:100%;text-align:center;margin-bottom:5mm"><span class="pageNumber"></span></div>`,
  });
  const n = (await pagina.pdf({ format: 'A4', preferCSSPageSize: true })).toString('latin1').match(/\/Type\s*\/Page[^s]/g).length;
  console.log('páginas:', n);
  await navegador.close();
})();
