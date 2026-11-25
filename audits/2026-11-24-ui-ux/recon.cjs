const {fs,ROOT,BASE,launch,capture}=require('./capture.cjs');
(async()=>{const b=await launch(),p=await b.newPage({viewport:{width:390,height:844}});await p.goto(BASE+'/login');await capture(p,'recon-login');console.log((await p.locator('body').innerText()).slice(0,3000));await b.close()})().catch(e=>{console.error(e);process.exit(1)});
