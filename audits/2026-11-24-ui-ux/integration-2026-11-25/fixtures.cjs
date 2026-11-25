// Reuses repository test fixtures; this never contacts a model or mutates business rules.
const {fs,path,ROOT,BASE,launch,capture}=require('./capture.cjs'),vm=require('vm');const ts=require(path.resolve('frontend/node_modules/typescript'));
function extract(file,from,to,context={}){let text=fs.readFileSync(file,'utf8');text=text.slice(text.indexOf(from),to?text.indexOf(to):undefined);const js=ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;const box={exports:{},...context};vm.runInNewContext(js,box);return box.exports;}
const R=extract('frontend/src/test/render.tsx','export const CLIENT');
const A=extract('frontend/src/test/admin.ts','export const ADMIN',null,R);
const P=extract('frontend/src/test/pharmacy.ts','const NOW',null,R);
const Q=extract('frontend/src/features/client/requests/RequestPage.test.tsx','const NOW','const MESSAGES',{...R});
// Locally scoped constants in existing test files are exported for this browser audit.
function constants(file,from,to,names,ctx){let text=fs.readFileSync(file,'utf8');text=text.slice(text.indexOf(from),text.indexOf(to));text+='\n'+names.map(n=>'export { '+n+' };').join('\n');let box={exports:{},...ctx};vm.runInNewContext(ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,box);return box.exports;}
const req=constants('frontend/src/features/client/requests/RequestPage.test.tsx','const NOW','const MESSAGES',['REQUEST','OFFER','REQUEST_ID','THREAD_ID'],R);
const ph=constants('frontend/src/features/pharmacy/PharmacyPortal.test.tsx','const NOW','function pharmacyApi',['HELD','ASK','NUMBERS'],R);
const none={items:[],next_cursor:null,total:0,server_now:R.CONFIG.server_now};
const data={R,A,P,req,ph};fs.writeFileSync(path.join(ROOT,'evidence/fixture-provenance.json'),JSON.stringify({sources:['frontend/src/test/render.tsx','frontend/src/test/admin.ts','frontend/src/test/pharmacy.ts','frontend/src/features/client/requests/RequestPage.test.tsx','frontend/src/features/pharmacy/PharmacyPortal.test.tsx'],mode:'Browser API interception using existing synthetic fixtures. UI behavior only; not live-model or backend integration evidence.'},null,2));
const records=[];
async function run(b,name,role,url,extra={},action){const ctx=await b.newContext({viewport:{width:390,height:844}});await ctx.addInitScript(()=>localStorage.setItem('dawalink.token','synthetic-fixture-token'));
 let messages=R.page([R.message(1,'client','I need Augmentin'),R.message(2,'agent','Which strength do you need?',{quick_replies:['1g']}),R.message(3,'agent','Here is an available option.',{cards:[R.RESERVE_CARD]}),R.message(4,'team','A person from DawaLink is helping you.')],{with_team:true});
 const routes={'GET /api/v1/auth/me':role==='admin'?A.ADMIN:role==='pharmacy'?P.PHARMACIST:R.CLIENT,'GET /api/v1/config/public':R.CONFIG,'GET /api/v1/districts':R.DISTRICTS,'GET /api/v1/admin/overview':A.OVERVIEW,'GET /api/v1/admin/pharmacies':{...none,items:[A.WAITING_ROW],total:1},['GET /api/v1/admin/pharmacies/'+A.PHARMACY_ID]:A.WAITING,'GET /api/v1/admin/escalations':{...none,items:[A.ESCALATION],total:1},['GET /api/v1/admin/escalations/'+A.ESCALATION_ID]:A.ESCALATION_DETAIL,'GET /api/v1/admin/clients':{...none,items:[A.CLIENT_ROW],total:1},['GET /api/v1/admin/clients/'+R.CLIENT.id]:A.CLIENT_DETAIL,'GET /api/v1/admin/answer-reports':{...none,items:[A.REPORT],total:1},'GET /api/v1/admin/audit':{...none,items:[A.AUDIT_EVENT],total:1},'GET /api/v1/requests':{...none,items:[req.REQUEST]},['GET /api/v1/requests/'+req.REQUEST_ID]:req.REQUEST,'GET /api/v1/offers':{...none,items:[req.OFFER]},'GET /api/v1/reservations':none,['GET /api/v1/reservations/'+R.RESERVATION.id]:R.RESERVATION,'GET /api/v1/watches':none,'GET /api/v1/conversations/active-chat':{conversation_id:R.CHAT_ID,kind:'chat'},['GET /api/v1/conversations/'+R.CHAT_ID+'/messages']:messages,['GET /api/v1/conversations/'+req.THREAD_ID+'/messages']:{...messages,conversation_id:req.THREAD_ID,kind:'request',request_id:req.REQUEST_ID},'GET /api/v1/pharmacy/me':P.PROFILE,'GET /api/v1/pharmacy/dashboard':ph.NUMBERS,'GET /api/v1/pharmacy/reservations':{...none,items:[ph.HELD],total:1},'GET /api/v1/pharmacy/early-release-asks':{...none,items:[ph.ASK]},...extra};
 const calls=[];await ctx.route('**/*',async route=>{let r=route.request(),u=new URL(r.url());if(!['localhost','127.0.0.1'].includes(u.hostname))return route.abort();if(u.port!=='8001')return route.continue();let key=r.method()+' '+u.pathname;calls.push(key);let body=routes[key];if(body===undefined)return route.fulfill({status:404,json:{error:{code:'NOT_FOUND',message:'No fixture for this endpoint'}}});if(typeof body==='function')body=body(r);if(body.__status)return route.fulfill({status:body.__status,json:body.body});return route.fulfill({json:body});});
 const p=await ctx.newPage();p.setDefaultTimeout(5000);try{await p.goto(BASE+url);await p.waitForTimeout(600);if(action)await action(p,calls,routes);for(let [v,s] of Object.entries({phone:{width:390,height:844},desktop:{width:1440,height:900}})){await p.setViewportSize(s);await capture(p,'fixture-'+name+'-'+v);}records.push({name,role,url,status:'rendered',calls});}catch(e){records.push({name,role,url,status:'blocked',reason:e.message,calls});console.log('BLOCKED',name,e.message.slice(0,200));}fs.writeFileSync(path.join(ROOT,'evidence/'+path.basename(process.argv[1],'.cjs')+'-states.json'),JSON.stringify(records,null,2));await ctx.close();}
if(require.main===module)(async()=>{const b=await launch();
await run(b,'assistant-clarification-card-team','client','/assistant');
await run(b,'request-active-offer','client','/requests/'+req.REQUEST_ID);
await run(b,'ticket-missed','client','/reservations/'+R.RESERVATION.id,{['GET /api/v1/reservations/'+R.RESERVATION.id]:{...R.RESERVATION,state:'EXPIRED_NO_SHOW',status_text:'Missed pickup',contestable:true}});
await run(b,'pharmacy-pending','pharmacy','/pharmacy',{'GET /api/v1/pharmacy/me':{...P.PROFILE,status:'PENDING'}});
await run(b,'pharmacy-rejected','pharmacy','/pharmacy',{'GET /api/v1/pharmacy/me':{...P.PROFILE,status:'REJECTED',status_reason:'Please correct your licence details.'}});
await run(b,'pharmacy-suspended','pharmacy','/pharmacy',{'GET /api/v1/pharmacy/me':{...P.PROFILE,status:'SUSPENDED'}});
await run(b,'pharmacy-counter','pharmacy','/pharmacy');
await run(b,'pharmacy-unavailable-dialog','pharmacy','/pharmacy',{},async p=>{await p.getByRole('button',{name:/Not available/i}).first().click();});
await run(b,'admin-pending-detail','admin','/admin/pharmacies/'+A.PHARMACY_ID);
await run(b,'admin-client-detail','admin','/admin/clients/'+R.CLIENT.id);
await run(b,'admin-escalation-detail','admin','/admin/escalations/'+A.ESCALATION_ID);
await run(b,'admin-reported-answer','admin','/admin/reports');
await run(b,'admin-audit-populated','admin','/admin/audit');
await run(b,'pharmacy-profile-error','pharmacy','/pharmacy',{'GET /api/v1/pharmacy/me':{__status:503,body:{error:{code:'SERVICE_UNAVAILABLE',message:'Synthetic outage'}}}},async p=>{await p.waitForTimeout(6000)});
await run(b,'admin-list-error','admin','/admin',{'GET /api/v1/admin/pharmacies':{__status:503,body:{error:{code:'SERVICE_UNAVAILABLE',message:'Synthetic outage'}}}});
await b.close();})().catch(e=>{console.error(e);process.exit(1)});

module.exports={run,data};
