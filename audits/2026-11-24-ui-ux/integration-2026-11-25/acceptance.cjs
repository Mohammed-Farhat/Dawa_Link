const assert=require('assert/strict');
const {fs,path,ROOT,BASE,API,launch,capture,login}=require('./capture.cjs');
const {run,data}=require('./fixtures.cjs');
const {R,P,req}=data;
const rows=[];
async function both(p,n){for(const[v,size]of Object.entries({phone:{width:390,height:844},desktop:{width:1440,height:900}})){await p.setViewportSize(size);await capture(p,n+'-'+v)}}
async function step(name,f){try{let detail=await f();rows.push({name,status:'passed',detail});console.log(name,'PASS')}catch(e){rows.push({name,status:'failed',error:e.message});console.log(name,'FAIL',e.message.slice(0,200))}fs.writeFileSync(path.join(ROOT,'evidence/acceptance.json'),JSON.stringify(rows,null,2))}
(async()=>{let b=await launch();
await run(b,'profile-retry','pharmacy','/pharmacy',{'GET /api/v1/pharmacy/me':{__status:503,body:{error:{code:'SERVICE_UNAVAILABLE',message:'Synthetic outage'}}}},async(p,calls,routes)=>{
 await p.waitForTimeout(12000);await step('F01 settled error and keyboard retry',async()=>{
 assert.equal(await p.getByRole('heading',{name:'Your pharmacy could not load',exact:true}).count(),1);
 await both(p,'profile-error');routes['GET /api/v1/pharmacy/me']=P.PROFILE;
 await p.getByRole('button',{name:'Try again',exact:true}).focus();await p.keyboard.press('Enter');await p.getByRole('heading',{name:'At the counter',exact:true}).waitFor();return {failedReads:calls.filter(x=>x==='GET /api/v1/pharmacy/me').length-1,recovered:true};
 });
});
await run(b,'responsive-profile','client','/me',{},async(p,calls)=>{await step('F02 profile and deletion drafts survive resize',async()=>{
 let edits=[];p.on('request',r=>{if(r.method()!=='GET'&&r.url().includes('/api/v1/'))edits.push(new URL(r.url()).pathname)});
 await p.getByLabel('First name',{exact:true}).fill('Unsaved Synthetic Name');await p.getByRole('button',{name:'Delete my account…',exact:true}).click();let field=p.getByLabel('Your password',{exact:true});await field.fill('Unsent-Synthetic-2026!');
 let observations=[];for(const w of [991,992,991,390,1440,390]){await p.setViewportSize({width:w,height:844});await p.waitForTimeout(120);observations.push({width:w,name:await p.getByLabel('First name',{exact:true}).inputValue(),draft:await field.inputValue(),focused:await field.evaluate(x=>x===document.activeElement),mainCount:await p.getByRole('main').count()})}
 assert(observations.every(x=>x.name==='Unsaved Synthetic Name'&&x.draft==='Unsent-Synthetic-2026!'&&x.focused&&x.mainCount===1));assert.equal(edits.length,0);return{observations,mutationCount:edits.length};
 })});
await run(b,'responsive-assistant','client','/assistant',{},async(p,calls)=>{await step('F02 assistant draft survives resize',async()=>{
 let field=p.getByLabel('Message',{exact:true});await field.fill('Unsent mixed draft مرحبا');for(let w of [991,992,991,390,1440,390]){await p.setViewportSize({width:w,height:844});await p.waitForTimeout(120);assert.equal(await field.inputValue(),'Unsent mixed draft مرحبا');assert(await field.evaluate(x=>x===document.activeElement));assert.equal(await p.getByRole('main').count(),1)}assert(!calls.some(x=>x.startsWith('POST')));return{draftPreserved:true,mutations:0};
 })});
await run(b,'responsive-request-confirmation','client','/requests/'+req.REQUEST_ID,{},async(p,calls)=>{await step('F02 request cancellation stays open',async()=>{
 await p.getByRole('button',{name:'Cancel this request',exact:true}).click();await p.getByRole('dialog').waitFor();for(let w of [991,992,991,390,1440,390]){await p.setViewportSize({width:w,height:844});await p.waitForTimeout(120);assert.equal(await p.getByRole('dialog').count(),1)}assert(!calls.some(x=>x.startsWith('POST')));return{dialogPreserved:true,mutations:0};
 })});
for(const state of ['PENDING','REJECTED','SUSPENDED'])await run(b,'pharmacy-'+state.toLowerCase(),'pharmacy','/pharmacy',{'GET /api/v1/pharmacy/me':{...P.PROFILE,status:state}});
await run(b,'request-detail','client','/requests/'+req.REQUEST_ID);
await run(b,'escalation-detail','admin','/admin/escalations/'+data.A.ESCALATION_ID);
await run(b,'assistant-support','client','/assistant');
const ctx=await b.newContext({viewport:{width:390,height:844}});await ctx.route('**/*',r=>['localhost','127.0.0.1'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());const p=await ctx.newPage();p.setDefaultTimeout(7000);
await login(p,'client01@demo.dawalink.test');
await step('A01 populated search has distinct region names',async()=>{await p.goto(BASE+'/search');await p.getByRole('searchbox').fill('a');await p.waitForTimeout(850);let names=await p.locator('section.medicine-group').evaluateAll(xs=>xs.map(x=>x.getAttribute('aria-label')));assert.equal(names.length,new Set(names).size);await both(p,'distinct-search-regions');return{names}});
await step('I02 location arrows wrap without requests',async()=>{await p.goto(BASE+'/me');let map=p.getByRole('radio',{name:'On the map',exact:true}),area=p.getByRole('radio',{name:'By area',exact:true});let changes=[];p.on('request',r=>{if(r.method()!=='GET'&&r.url().includes('/api/v1/'))changes.push(new URL(r.url()).pathname)});await map.focus();await p.keyboard.press('ArrowRight');assert.equal(await area.getAttribute('aria-checked'),'true');assert(await area.evaluate(x=>x===document.activeElement));await p.keyboard.press('ArrowDown');assert.equal(await map.getAttribute('aria-checked'),'true');assert.equal(changes.length,0);await both(p,'radio-keyboard');return{mutations:0}});
// Advance only the disposable database through its supported clock UI.
let adminCtx=await b.newContext();await adminCtx.route('**/*',r=>['localhost','127.0.0.1'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());let admin=await adminCtx.newPage();const cp=require('child_process');let code=cp.execFileSync('backend/.venv/bin/python',['-c',"import json,pyotp;print(pyotp.TOTP(json.load(open('/private/tmp/dawalink-ui-integration-admin.json'))['key']).now())"]).toString().trim();await login(admin,'admin@audit.dawalink.test',code);await admin.goto(BASE+'/admin/clock');for(let i=0;i<4;i++){let text=await admin.locator('body').innerText();let h=Number(text.match(/The app's time:.*?(\d{2}):\d{2}/)?.[1]);if(h>=8&&h<20)break;await admin.getByRole('button',{name:'+6 h',exact:true}).click();await admin.waitForTimeout(300)}await capture(admin,'demo-clock');
// Separate browser session: admin login above replaced the shared context's token.
const clientCtx=await b.newContext({viewport:{width:390,height:844}});await clientCtx.route('**/*',r=>['localhost','127.0.0.1'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());const client=await clientCtx.newPage();client.setDefaultTimeout(7000);await login(client,'client01@demo.dawalink.test');
await step('F03 live ordinary search watch create list stop and resize',async()=>{
 await client.goto(BASE+'/medicines');await client.waitForTimeout(500);for(const button of await client.getByRole('button',{name:/^Stop watching /}).all()){await button.click();await client.waitForTimeout(300)}
 await client.goto(BASE+'/search');await client.getByRole('searchbox').fill('APO-AZITHROMYCIN Z');await client.getByRole('region',{name:'Find the exact medicine',exact:true}).waitFor();await both(client,'catalog-discovery');let match=client.getByRole('region',{name:'Find the exact medicine',exact:true}).getByRole('button').filter({hasText:'APO-AZITHROMYCIN Z'}).first();await match.click();let selected=new URL(client.url()).searchParams.get('product');assert(selected);await client.getByRole('button',{name:'Notify me if it appears',exact:true}).click();const price=client.getByLabel('The most you would pay for a pack, in LBP (optional)',{exact:true});await price.fill('999999999');for(let w of [991,992,991,390,1440,390]){await client.setViewportSize({width:w,height:844});await client.waitForTimeout(120);assert.equal(await price.inputValue(),'999999999')};await both(client,'watch-draft-preserved');await client.getByRole('button',{name:'Notify me for 6 hours',exact:true}).click();await client.getByText(/We'll tell you if it appears before/).waitFor();await both(client,'watch-created');await client.goto(BASE+'/medicines');await client.getByRole('button',{name:/^Stop watching / }).waitFor();await both(client,'watch-listed');await client.getByRole('button',{name:/^Stop watching / }).click();await client.waitForTimeout(450);assert.equal(await client.getByRole('button',{name:/^Stop watching / }).count(),0);await both(client,'watch-stopped');return{selectedProduct:selected,created:true,listed:true,stopped:true,draftPreserved:true};
});
await clientCtx.close();await adminCtx.close();await ctx.close();await b.close();if(rows.some(x=>x.status==='failed'))process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
