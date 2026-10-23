const { chromium } = require('playwright');
(async()=>{const b=await chromium.launch({channel:'chrome'});const p=await b.newPage({deviceScaleFactor:3,viewport:{width:1200,height:900}});
await p.goto('file://'+__dirname+'/tex.html');await p.evaluate(()=>document.fonts.ready);await p.waitForTimeout(800);
console.log(await p.evaluate(()=>['Familjen Grotesk','IBM Plex Mono','Instrument Serif','Bebas Neue'].map(f=>f+':'+document.fonts.check('20px "'+f+'"'))));
for(const id of ['pass','rcpt','ruler','book','tape1','tape2','tape1h','tape2h'])await p.locator('#'+id).screenshot({path:id+'.png',omitBackground:true});
await b.close()})();
