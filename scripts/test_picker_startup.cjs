// Execute maintained main/renderer code with explicit Electron/desktop fixtures.
// No real clients, compositor, account files or desktop commands are invoked.
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');
const {EventEmitter}=require('node:events');
const assert=require('node:assert/strict');
const test=require('node:test');
const root=join(__dirname,'..');
const src=process.env.DPAD_PICKER_TEST_SOURCE||join(root,'launcher/src');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

async function mainFixture(){
 const ipc=new Map(),timers=new Map(),events=[],commands=[],children=[];let nextTimer=0,titles=[];
 class Window extends EventEmitter{
  constructor(){super();this.webContents={send:(...args)=>events.push(args)};}
  loadFile(){} focus(){} maximize(){} static getAllWindows(){return [true];}
 }
 const app=new EventEmitter();app.whenReady=()=>Promise.resolve();
 const context=vm.createContext({Buffer,console:{log(){}},process:{env:{PATH:'/fixture',HOME:'/fixture/home',SWAYSOCK:'/fixture/desktop.sock',DPAD_EPIC_BACKEND:'faugus'}},
  setTimeout:()=>({unref(){}}),setInterval:fn=>{const id=++nextTimer;timers.set(id,fn);return id},clearInterval:id=>timers.delete(id),
  __dirname:src,require:name=>{
   if(name==='electron')return {app,BrowserWindow:Window,ipcMain:{handle:(id,handler)=>ipc.set(id,handler)}};
   if(name==='fs')return {existsSync:()=>true,appendFileSync(){}};
   if(name==='child_process')return {spawn:()=>{const child=new EventEmitter();child.pid=100+children.length;child.unref=()=>{};children.push(child);return child},
    execSync:cmd=>{commands.push(cmd);return Buffer.from(cmd.includes('get_tree')?JSON.stringify({nodes:titles.map(name=>({type:'con',name}))}):'[{}]')}};
   if(name==='./sdl_manager.cjs')return {pollGamepads:()=>[],mapToWebApi:value=>value};
   if(name==='./store_lifecycle.cjs'){
    const policy=require(join(src,'store_lifecycle.cjs'));
    return {...policy,clearOwnedTimer:(map,id,owner)=>policy.clearOwnedTimer(map,id,owner,timer=>timers.delete(timer))};
   }
   if(name.startsWith('./'))return require(join(src,name));
   return require(name);
  }});
 vm.runInContext(readFileSync(join(src,'main.js'),'utf8'),context);await flush();
 return {events,commands,children,timers,launch:id=>ipc.get('launch-store')({},id),titles:value=>{titles=value},
  tick:count=>{for(let i=0;i<count;i++)for(const fn of [...timers.values()])fn()}};
}

test('startup timeout preserves the picker, reports uncertainty and does not create a second client',async()=>{
 const f=await mainFixture();assert.equal((await f.launch('epic')).ok,true);
 f.tick(1800);
 assert.ok(f.events.some(event=>event[0]==='store-launch-failed'&&event[1]==='epic'));
 assert.equal(f.events.some(event=>event[0]==='store-visible'),false);
 assert.equal(f.commands.some(command=>command.includes('move container to scratchpad')),false);
 assert.equal(f.timers.size,0);assert.equal((await f.launch('epic')).ok,false);assert.equal(f.children.length,1);
});
test('a confirmed store window hides the picker and reports the selected store',async()=>{
 const f=await mainFixture();await f.launch('epic');f.titles(['Epic Games Launcher']);f.tick(1);
 assert.ok(f.events.some(event=>event[0]==='store-visible'&&event[1]==='epic'));
 assert.ok(f.commands.some(command=>command.includes('move container to scratchpad')));assert.equal(f.timers.size,0);
});
test('a superseded child exit/error cannot release or notify its new store owner',async()=>{
 const f=await mainFixture();await f.launch('epic');const old=f.children[0];old.emit('error',Error('fixture spawn failed'));
 await f.launch('epic');const fresh=f.children[1],before=f.events.length;
 old.emit('exit',1,null);old.emit('error',Error('fixture late error'));
 assert.equal(f.events.length,before);assert.equal(f.timers.size,1);
 f.titles(['Epic Games Launcher']);f.tick(1);
 const result=await f.launch('epic');assert.equal(result.resumed,true);assert.equal(result.pid,fresh.pid);assert.equal(f.children.length,2);
});

async function rendererFixture(){
 class Element{
  constructor(){this.children=[];this.attributes={};this.listeners={};this.style={setProperty(){}};
   const classes=new Set();this.classList={add:value=>classes.add(value),remove:value=>classes.delete(value),contains:value=>classes.has(value),
    toggle:(value,enabled)=>enabled?classes.add(value):classes.delete(value)};}
  set innerHTML(value){this.html=value;if(value==='')this.children=[]}get innerHTML(){return this.html}
  appendChild(value){this.children.push(value)}setAttribute(key,value){this.attributes[key]=value}
  addEventListener(key,fn){this.listeners[key]=fn}scrollIntoView(){}getBoundingClientRect(){return {left:0,top:0,width:100,height:100}}
 }
 const elements=Object.fromEntries(['grid','launchOverlay','launchLogo','launchName','reloadStores'].map(key=>[key,new Element()]));
 const handlers={},document={getElementById:id=>elements[id],createElement:()=>new Element(),body:new Element()};
 const stores=[{id:'epic',name:'Epic Games',available:true},{id:'steam',name:'Steam',available:true}];
 let request=async()=>({ok:true}),catalog=async()=>stores;
 const dpad={getStores:()=>catalog(),pollGamepads:async()=>[],launchStore:id=>request(id)};
 for(const name of ['onStoreVisible','onStoreExited','onStoreLaunchFailed','onStoreInstalling'])dpad[name]=handler=>{handlers[name]=handler};
 const context=vm.createContext({document,window:{dpad,addEventListener(){}},setTimeout:()=>0,clearTimeout(){}});
 vm.runInContext(readFileSync(join(src,'renderer.js'),'utf8'),context);await flush();
 return {elements,handlers,document,context,run:code=>vm.runInContext(code,context),request:fn=>{request=fn},catalog:fn=>{catalog=fn}};
}
test('unrelated store events cannot dismiss or replace another store startup overlay',async()=>{
 const f=await rendererFixture();await f.run('launch()');
 f.handlers.onStoreInstalling('steam');f.handlers.onStoreVisible('steam');f.handlers.onStoreExited('steam');await flush();
 assert.equal(f.elements.launchOverlay.classList.contains('show'),true);assert.match(f.elements.launchName.textContent,/Launching Epic Games/);
 f.handlers.onStoreInstalling('epic');assert.match(f.elements.launchName.textContent,/Waiting for Epic Games/);
 f.handlers.onStoreVisible('epic');assert.equal(f.elements.launchOverlay.classList.contains('show'),false);
 assert.equal(f.elements.launchOverlay.attributes['aria-hidden'],'true');
});
test('a delayed failed request cannot dismiss a later store after returning to the picker',async()=>{
 const f=await rendererFixture();let release;
 f.request(()=>new Promise(resolve=>{release=resolve}));const old=f.run('launch()');
 f.run('dismissOverlay();focus(1)');f.request(async()=>({ok:true}));await f.run('launch()');
 release({ok:false,error:'fixture late response'});await old;
 assert.equal(f.elements.launchOverlay.classList.contains('show'),true);assert.match(f.elements.launchName.textContent,/Launching Steam/);
});
test('IPC failure leaves usable retry feedback and event refresh preserves keyboard selection',async()=>{
 const f=await rendererFixture();f.run('focus(1)');f.request(async()=>{throw Error('fixture transport lost')});await f.run('launch()');
 assert.equal(f.elements.launchOverlay.classList.contains('show'),false);
 assert.match(f.document.body.children[0].textContent,/Steam startup could not be confirmed/);
 f.handlers.onStoreExited('epic');await flush();
 assert.equal(f.run('cards[focusIndex].store.id'),'steam');assert.match(f.run('statusPill(cards[focusIndex].store).text'),/Startup unconfirmed/);
 assert.equal(f.run('statusPill({id:"new",available:true}).text'),'Ready to open');
});

test('return to the picker refreshes status without losing selected store',async()=>{
 const f=await rendererFixture();await f.run('launch()');f.handlers.onStoreInstalling('epic');f.run('dismissOverlay()');
 assert.match(f.elements.grid.children[0].innerHTML,/Waiting for window/);
 assert.equal(f.run('cards[focusIndex].store.id'),'epic');
 f.handlers.onStoreLaunchFailed('epic','fixture delayed failure');
 assert.match(f.elements.grid.children[0].innerHTML,/Startup unconfirmed/);
});
test('catalog transport loss exposes retry and preserves existing choices',async()=>{
 const f=await rendererFixture();f.run('focus(1)');f.catalog(async()=>{throw Error('fixture catalog lost')});
 await f.run('refreshStores()');assert.equal(f.elements.reloadStores.hidden,false);assert.equal(f.elements.grid.children.length,2);
 f.catalog(async()=>[{id:'epic',name:'Epic Games',available:true},{id:'steam',name:'Steam',available:true}]);
 await f.elements.reloadStores.listeners.click();assert.equal(f.elements.reloadStores.hidden,true);assert.equal(f.run('cards[focusIndex].store.id'),'steam');
});
